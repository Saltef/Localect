"""Perturbation tests for the Critic and the Arbiter.

A verifier is only worth trusting if it catches faults you plant. This module
takes a finished run, injects one known fault into the final text, sends the
result back through exactly what the pipeline runs after a rewrite (strip
citations, apply the locale conventions, Critic, Arbiter), and records which
layer caught it. Recall per fault kind, by layer, plus the false-alarm rate on
untouched runs, is the Critic's score.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field

from .locales import load_starter_profiles
from .pipeline import LANG_NAMES, polish, verify
from .schemas import FlagKind, LocaleProfile, Result, Rewrite
from .text import numbers, to_eastern, to_western

MUTATIONS = ("drop_preserved", "change_number", "wrong_greeting", "add_promise",
             "leak_citation", "slang")

# Flag kinds that count as catching each fault.
EXPECTED: dict[str, set[FlagKind]] = {
    "drop_preserved": {FlagKind.drifted, FlagKind.missing_item},
    "change_number": {FlagKind.drifted, FlagKind.unsupported_claim},
    "wrong_greeting": {FlagKind.tone_off, FlagKind.cultural_risk, FlagKind.drifted},
    "add_promise": {FlagKind.unsupported_claim, FlagKind.drifted},
    "leak_citation": {FlagKind.tone_off, FlagKind.drifted},
    "slang": {FlagKind.tone_off, FlagKind.cultural_risk},
}

_PROMISE = {
    "en": "You will also receive a full refund and a $50 gift card.",
    "ar": "وهتحصل كمان على استرداد كامل وكوبون هدية بقيمة ٥٠ دولار.",
    "es": "Además recibirás un reembolso completo y una tarjeta de regalo de $50.",
    "pt": "Além disso, você receberá um reembolso total e um vale-presente de $50.",
    "fr": "Vous recevrez également un remboursement intégral et une carte cadeau de 50 $.",
    "de": "Außerdem erhalten Sie eine vollständige Rückerstattung und einen 50-$-Gutschein.",
    "ja": "さらに全額返金と50ドルのギフトカードもお送りします。",
}
_SLANG = {"en": "lol ", "ar": "يا صاحبي، ", "es": "wey, ", "pt": "mano, ", "fr": "wesh, ",
          "de": "ey Alter, ", "ja": "おい、"}


@dataclass
class PerturbScore:
    model: str
    critic_model: str
    sample_id: str
    mutation: str
    applicable: bool = True
    detected: bool = False
    neutralized: bool = False  # a deterministic step undid the fault
    by_critic: bool = False  # the Critic raised an expected flag on that segment
    by_arbiter: bool = False  # the Arbiter's own checks raised one
    segment_id: str = ""
    detail: str = ""
    flags: list[str] = field(default_factory=list)


def _body_segment(result: Result):
    """The segment most worth corrupting: one that carries a claim, else the
    longest one that is not the greeting or the sign-off."""
    segs = result.rewrite.segments
    claims = {s.id for s in result.draft.segments if s.claims}
    inner = segs[1:-1] if len(segs) > 2 else segs
    with_claims = [s for s in inner if s.id in claims]
    pool = with_claims or inner or segs
    return max(pool, key=lambda s: len(s.text)) if pool else None


def _other_greeting(locale: LocaleProfile) -> str:
    for p in load_starter_profiles():
        if p.language != locale.language and p.greeting:
            return p.greeting.replace("{name}", "").replace(" ,", ",").strip()
    return "Hey buddy,"


def mutate(result: Result, mutation: str) -> tuple[Rewrite, str, str] | None:
    """Return (mutated rewrite, segment id, what changed), or None when the
    fault cannot be planted in this run."""
    rw = copy.deepcopy(result.rewrite)
    by_id = {s.id: s for s in rw.segments}
    lang = result.locale.language
    seg = _body_segment(result)
    if seg is None:
        return None
    target = by_id[seg.id]

    if mutation == "drop_preserved":
        for item in result.reading.must_preserve:
            for s in rw.segments:
                if item in s.text:
                    s.text = s.text.replace(item, "").replace("  ", " ").strip()
                    return rw, s.id, f"removed '{item}'"
                w = to_western(item)
                if w != item and w in to_western(s.text):
                    s.text = to_western(s.text).replace(w, "").replace("  ", " ").strip()
                    return rw, s.id, f"removed '{item}'"
        return None

    if mutation == "change_number":
        covered = {n for it in result.reading.must_preserve for n in numbers(it)}
        for s in rw.segments:
            for n in sorted(numbers(s.text) - covered, key=len):
                if n in to_western(s.text):
                    new = str(int(n) + 7)
                    eastern = result.locale.formats.numerals == "eastern-arabic"
                    src = to_eastern(n) if eastern and to_eastern(n) in s.text else n
                    dst = to_eastern(new) if src != n else new
                    s.text = s.text.replace(src, dst, 1)
                    return rw, s.id, f"changed {n} to {new}"
        return None

    if mutation == "wrong_greeting":
        first = rw.segments[0]
        g = _other_greeting(result.locale)
        if first.text == g:
            return None
        first.text = g
        return rw, first.id, f"greeting replaced with '{g}'"

    if mutation == "add_promise":
        p = _PROMISE.get(lang, _PROMISE["en"])
        target.text = f"{target.text} {p}"
        return rw, target.id, "appended an unsupported promise"

    if mutation == "leak_citation":
        target.text = f"{target.text} [kb:12:0]"
        return rw, target.id, "appended a source id"

    if mutation == "slang":
        target.text = _SLANG.get(lang, _SLANG["en"]) + target.text
        return rw, target.id, "prepended slang"

    raise ValueError(f"unknown mutation {mutation!r}")


async def perturb_one(result: Result, mutation: str, critic_model, user_name: str,
                      contact_name: str = "") -> PerturbScore:
    row = PerturbScore(model=result.model, critic_model=critic_model.name,
                       sample_id="", mutation=mutation)
    out = mutate(result, mutation)
    if out is None:
        row.applicable = False
        return row
    rw, seg_id, detail = out
    row.segment_id, row.detail = seg_id, detail
    original = {s.id: s.text for s in result.rewrite.segments}
    mutated = {s.id: s.text for s in rw.segments}

    polish(rw, result.locale, contact_name, user_name)
    after = {s.id: s.text for s in rw.segments}
    if after.get(seg_id) == original.get(seg_id) and mutated.get(seg_id) != original.get(seg_id):
        row.neutralized = True

    errors: list[str] = []
    cq, flags, _status, _ledger = await verify(
        critic_model, result.draft, rw, result.locale, result.sources,
        result.reading.must_preserve,
        LANG_NAMES.get(result.user_language, result.user_language), contact_name, user_name,
        errors)
    expected = EXPECTED[mutation]
    critic_hits = [f for f in cq.flags if f.kind in expected]
    critic_keys = {(f.segment_id, f.kind, f.span) for f in cq.flags}
    arbiter_hits = [f for f in flags if f.kind in expected
                    and (f.segment_id, f.kind, f.span) not in critic_keys]
    row.by_critic = any(f.segment_id == seg_id for f in critic_hits) or (
        bool(critic_hits) and mutation == "wrong_greeting")
    row.by_arbiter = any(f.segment_id == seg_id for f in arbiter_hits)
    row.flags = [f"{f.segment_id}:{f.kind.value}:{f.severity}" for f in flags]
    row.detected = row.neutralized or row.by_critic or row.by_arbiter
    return row


async def run_perturb(results: list[tuple[str, Result]], critic_model, user_name: str,
                      on_row=None) -> list[PerturbScore]:
    rows: list[PerturbScore] = []
    for sample_id, result in results:
        for m in MUTATIONS:
            row = await perturb_one(result, m, critic_model, user_name)
            row.sample_id = sample_id
            rows.append(row)
            if on_row:
                on_row(row)
    return rows


def false_alarms(results: list[tuple[str, Result]]) -> dict[str, int]:
    """On untouched runs: how many did the Critic block, and how many did the
    Arbiter's own checks block or warn on."""
    critic = sum(1 for _, r in results if any(f.severity == "block" for f in r.critique.flags))
    crit_keys = {(id(r), f.segment_id, f.kind, f.span)
                 for _, r in results for f in r.critique.flags}
    arb_block = sum(1 for _, r in results if any(
        f.severity == "block" and (id(r), f.segment_id, f.kind, f.span) not in crit_keys
        for f in r.flags))
    arb_warn = sum(1 for _, r in results if any(
        f.severity == "warn" and (id(r), f.segment_id, f.kind, f.span) not in crit_keys
        for f in r.flags))
    return {"runs": len(results), "critic_block": critic, "arbiter_block": arb_block,
            "arbiter_warn": arb_warn}


def _pct(k: int, n: int) -> str:
    return f"{100 * k / n:3.0f}%"


def render_perturb(rows: list[PerturbScore], alarms: dict[str, int] | None = None) -> str:
    by_model: dict[str, list[PerturbScore]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    lines = []
    for model, rs in by_model.items():
        judge = rs[0].critic_model if rs and rs[0].critic_model != model else ""
        lines.append(f"\nPerturbations on {model}" + (f" (judged by {judge})" if judge else ""))
        lines.append(f"  {'fault':16} {'n':>3} {'caught':>7} {'critic':>7} {'arbiter':>8} "
                     f"{'neutral':>8}")
        for m in MUTATIONS:
            ms = [r for r in rs if r.mutation == m and r.applicable]
            n = len(ms)
            if not n:
                lines.append(f"  {m:16} {0:>3} {'-':>7} {'-':>7} {'-':>8} {'-':>8}")
                continue

            lines.append(f"  {m:16} {n:>3} {_pct(sum(r.detected for r in ms), n):>7} "
                         f"{_pct(sum(r.by_critic for r in ms), n):>7} "
                         f"{_pct(sum(r.by_arbiter for r in ms), n):>8} "
                         f"{_pct(sum(r.neutralized for r in ms), n):>8}")
    if alarms and alarms.get("runs"):
        n = alarms["runs"]
        lines.append(f"  false alarms on {n} untouched runs: critic blocked "
                     f"{alarms['critic_block']}, arbiter blocked {alarms['arbiter_block']}, "
                     f"arbiter warned {alarms['arbiter_warn']}")
    return "\n".join(lines)


def perturb_to_dicts(rows: list[PerturbScore]) -> list[dict]:
    return [asdict(r) for r in rows]
