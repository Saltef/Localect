"""``envoy eval``: run a sample set through one or more models and score it.

Every check is deterministic and needs no human. Checks decide pass or fail:

- locale: the reply resolved to the sample's locale (or language)
- preserved: every must-preserve item that reached the draft survived the rewrite
- fact: each expected fact is present; numbers match as whole tokens in any digit script
- no_wrong: no value that would contradict the knowledge base
- terms: glossary terms present
- no_leaks: no source ids in the text
- no_forbidden: none of the sample's forbidden phrases (injection samples)
- verified: no stage failed

Greeting and sign-off are enforced in code after every stage, so they are
reported as invariants, separately: they cannot fail, and counting them as
passes would flatter the model.

With ``--perturb``, every finished run is also corrupted in six known ways and
sent back through the Critic and the Arbiter; see ``envoy.perturb``.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from . import db
from .config import Settings, data_dir
from .conventions import rendered_greeting, rendered_signoff
from .demo import seed_demo
from .evalset import SETS, Sample, load
from .evalx.dialect import DialectScorer, discover, matches
from .locales import seed_locales
from .models import build_model
from .perturb import (
    PerturbScore,
    false_alarms,
    perturb_to_dicts,
    render_perturb,
    run_perturb,
)
from .pipeline import PipelineError, compose, critic_model_for
from .schemas import ComposeRequest, Result
from .text import has_value, strip_citations, to_western
from .tools import DirectTools

CHECK_ORDER = ["locale", "preserved", "fact", "no_wrong", "terms", "no_leaks", "no_forbidden",
               "verified"]
INVARIANTS = ["greeting", "signoff"]


@dataclass
class RunScore:
    model: str
    sample_id: str
    set: str
    label: str
    seconds: float
    critic_model: str = ""
    status: str = ""
    locale: str = ""
    error: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)  # why each failed check failed
    invariants: dict[str, bool] = field(default_factory=dict)
    reading: dict[str, Any] = field(default_factory=dict)  # what the Reader reported
    flags: list[str] = field(default_factory=list)  # segment:kind:severity reason
    flags_block: int = 0
    flags_warn: int = 0
    suggestions: int = 0
    revisions: int = 0
    message: str = ""
    draft_text: str = ""
    final_text: str = ""
    dialect: dict[str, Any] = field(default_factory=dict)  # draft vs final, when a scorer exists
    result: Result | None = field(default=None, repr=False, compare=False)

    @property
    def passed(self) -> bool:
        return not self.error and all(self.checks.values()) and self.status != "escalate"

    @property
    def failed_checks(self) -> list[str]:
        return [k for k in CHECK_ORDER if not self.checks.get(k, True)]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("result", None)
        d["passed"] = self.passed
        return d


def score(result: Result, sample: Sample, user_name: str
          ) -> tuple[dict[str, bool], dict[str, bool]]:
    final = result.final_text
    low = to_western(final).lower()
    exp = sample.locale
    draft_low = to_western(result.draft.text()).lower()
    checks = {
        "locale": result.locale.locale == exp or result.locale.locale.startswith(exp + "-"),
        # The Arbiter's rule: anything preserved into the draft must survive the rewrite.
        "preserved": all(has_value(final, item) for item in result.reading.must_preserve
                         if has_value(draft_low, item)),
        "fact": all(any(has_value(final, alt) for alt in alternatives)
                    for alternatives in sample.facts),
        "no_wrong": not any(has_value(final, v) for v in sample.wrong),
        "terms": all(t.lower() in low for t in sample.terms),
        "no_leaks": strip_citations(final) == final.strip(),
        "no_forbidden": not any(has_value(final, p) for p in sample.forbid),
        "verified": not result.stage_errors,
    }
    invariants = {
        "greeting": final.startswith(rendered_greeting(result.locale, "")),
        "signoff": final.rstrip().endswith(rendered_signoff(result.locale, user_name).rstrip()),
    }
    return checks, invariants


def explain(result: Result, sample: Sample, checks: dict[str, bool]) -> dict[str, str]:
    """One line per failed check saying what was looked for and not found (or
    found and not wanted), so a failure can be diagnosed from the JSON alone."""
    final = result.final_text
    low = to_western(final).lower()
    draft_low = to_western(result.draft.text()).lower()
    out: dict[str, str] = {}
    if not checks.get("locale", True):
        out["locale"] = (f"resolved to {result.locale.locale}, expected {sample.locale}; the "
                         f"Reader said language={result.reading.language!r} "
                         f"region_guess={result.reading.region_guess!r}")
    if not checks.get("preserved", True):
        lost = [i for i in result.reading.must_preserve
                if has_value(draft_low, i) and not has_value(final, i)]
        out["preserved"] = "dropped by the rewrite: " + ", ".join(lost)
    if not checks.get("fact", True):
        missing = [" | ".join(alts) for alts in sample.facts
                   if not any(has_value(final, a) for a in alts)]
        out["fact"] = "not in the reply: " + "; ".join(missing)
    if not checks.get("no_wrong", True):
        out["no_wrong"] = "contradicts the knowledge base: " + ", ".join(
            v for v in sample.wrong if has_value(final, v))
    if not checks.get("terms", True):
        out["terms"] = "glossary terms missing: " + ", ".join(
            t for t in sample.terms if t.lower() not in low)
    if not checks.get("no_leaks", True):
        out["no_leaks"] = "source ids left in the text"
    if not checks.get("no_forbidden", True):
        out["no_forbidden"] = "forbidden phrase present: " + ", ".join(
            p for p in sample.forbid if has_value(final, p))
    if not checks.get("verified", True):
        out["verified"] = "; ".join(result.stage_errors)[:300]
    return out


def _body(segments) -> str:
    """The reply without its greeting and sign-off: those are applied in code
    and identical in draft and final, so they would only dilute the measure."""
    inner = segments[1:-1] if len(segments) > 2 else segments
    return "\n".join(s.text for s in inner)


def dialect_ablation(result: Result, scorer: DialectScorer) -> dict[str, Any]:
    """Classify the Drafter's body and the Rewriter's body with the same judge."""
    draft_label = scorer.predict(_body(result.draft.segments))
    final_label = scorer.predict(_body(result.rewrite.segments))
    target = result.locale.locale
    return {"scorer": scorer.name, "target": target, "draft": draft_label,
            "final": final_label, "draft_ok": matches(draft_label, target),
            "final_ok": matches(final_label, target)}


def select(samples: list[Sample], indexes: list[int] | None) -> list[Sample]:
    if indexes is None:
        return samples
    return [samples[i] for i in indexes if 0 <= i < len(samples)]


async def run_eval(settings: Settings, models: list[str] | None = None,
                   indexes: list[int] | None = None, con=None, on_row=None,
                   sample_set: str = "demo", samples: list[Sample] | None = None,
                   critic_model: str | None = None,
                   scorers: dict[str, DialectScorer] | None = None) -> list[RunScore]:
    con = con if con is not None else db.connect(settings.db_path)
    seed_locales(con)
    seed_demo(con)
    scorers = discover(data_dir()) if scorers is None else scorers
    if critic_model:
        settings.role_models = {**settings.role_models, "critic": critic_model}
    base = build_model(settings)
    names = models or [getattr(base, "model", base.name)]
    chosen = select(samples if samples is not None else load(sample_set), indexes)
    rows: list[RunScore] = []
    for name in names:
        model = base.with_model(name) if hasattr(base, "with_model") and name != getattr(
            base, "model", None) else base
        for sample in chosen:
            t0 = time.perf_counter()
            row = RunScore(model=model.name, sample_id=sample.id, set=sample.set,
                           label=sample.label, seconds=0.0, message=sample.text)
            try:
                r = await compose(ComposeRequest(message=sample.text), settings=settings,
                                  model=model, tools=DirectTools(con), con=con)
                row.status, row.locale = r.status.value, r.locale.locale
                row.critic_model = r.critic_model
                row.checks, row.invariants = score(r, sample, settings.user_name)
                row.details = explain(r, sample, row.checks)
                row.reading = {"language": r.reading.language,
                               "region_guess": r.reading.region_guess,
                               "must_preserve": list(r.reading.must_preserve),
                               "asks": list(r.reading.asks)}
                row.flags = [f"{f.segment_id}:{f.kind.value}:{f.severity} {f.reason}"[:200]
                             for f in r.flags]
                row.flags_block = sum(1 for f in r.flags if f.severity == "block")
                row.flags_warn = sum(1 for f in r.flags if f.severity == "warn")
                row.suggestions = len(r.suggestions)
                row.revisions = r.revisions
                row.draft_text = r.draft.text()
                row.final_text = r.final_text
                row.result = r
                if (scorer := scorers.get(r.locale.language)) is not None:
                    row.dialect = dialect_ablation(r, scorer)
            except PipelineError as e:
                row.error = str(e)[:500]
            row.seconds = round(time.perf_counter() - t0, 1)
            rows.append(row)
            if on_row:
                on_row(row)
    return rows


async def run_perturbations(rows: list[RunScore], settings: Settings, on_row=None
                            ) -> tuple[list[PerturbScore], dict[str, int]]:
    """Corrupt every run that has a result and see what the verifier catches."""
    base = build_model(settings)
    out: list[PerturbScore] = []
    alarms = {"runs": 0, "critic_block": 0, "arbiter_block": 0, "arbiter_warn": 0}
    by_model: dict[str, list[tuple[str, Result]]] = {}
    for r in rows:
        if r.result is not None:
            by_model.setdefault(r.model, []).append((r.sample_id, r.result))
    for _model_name, results in by_model.items():
        drafter = results[0][1]
        model = base
        if hasattr(base, "with_model") and drafter.model != base.name:
            model = base.with_model(drafter.model.split(":", 1)[-1])
        judge = critic_model_for(settings, model)
        out += await run_perturb(results, judge, settings.user_name, on_row=on_row)
        clean = [(sid, r) for sid, r in results
                 if all(score(r, _sample_by_id(rows, sid), settings.user_name)[0].values())]
        fa = false_alarms(clean)
        for k in alarms:
            alarms[k] += fa[k]
    return out, alarms


def _sample_by_id(rows: list[RunScore], sample_id: str) -> Sample:
    for s in load("all"):
        if s.id == sample_id:
            return s
    row = next(r for r in rows if r.sample_id == sample_id)
    return Sample(id=sample_id, label=row.label, text="", locale=row.locale)


def render_table(rows: list[RunScore]) -> str:
    lines = []
    by_model: dict[str, list[RunScore]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    for model, rs in by_model.items():
        passed = sum(1 for r in rs if r.passed)
        judge = next((r.critic_model for r in rs if r.critic_model), "")
        lines.append(f"\n{model}: {passed}/{len(rs)} passed, "
                     f"{sum(r.seconds for r in rs):.0f}s total"
                     + (f", critic judged by {judge}" if judge else ""))
        lines.append(f"  {'sample':10} {'result':7} {'status':9} {'locale':7} {'s':>5}  checks")
        for r in rs:
            if r.error:
                lines.append(f"  {r.sample_id:10} {'ERROR':7} {'':9} {'':7} {r.seconds:>5}  "
                             f"{r.error}")
                continue
            failed = r.failed_checks
            marks = "ok" if not failed else "FAIL " + ",".join(failed)
            extra = []
            broken = [k for k in INVARIANTS if not r.invariants.get(k, True)]
            if broken:
                extra.append("invariant " + ",".join(broken))
            if r.flags_block or r.flags_warn:
                extra.append(f"flags {r.flags_block}b/{r.flags_warn}w")
            if r.suggestions:
                extra.append(f"{r.suggestions} sugg")
            if r.revisions:
                extra.append("revised")
            lines.append(f"  {r.sample_id:10} {('pass' if r.passed else 'fail'):7} "
                         f"{r.status:9} {r.locale:7} {r.seconds:>5}  {marks}"
                         + (f"  ({', '.join(extra)})" if extra else ""))
            for k in failed:
                if r.details.get(k):
                    lines.append(f"{'':13}why {k}: {r.details[k][:160]}")
        lines += render_dialect(rs)
    return "\n".join(lines)


def render_dialect(rows: list[RunScore]) -> list[str]:
    """Per locale: how often the draft body, then the final body, was
    classified as the target dialect. The gap is the Rewriter's work."""
    scored = [r for r in rows if r.dialect]
    if not scored:
        return []
    lines = ["  dialect (judged by " + ", ".join(sorted({r.dialect["scorer"] for r in scored}))
             + "):  locale  n  draft  final"]
    by_locale: dict[str, list[RunScore]] = {}
    for r in scored:
        by_locale.setdefault(r.dialect["target"], []).append(r)
    for locale, rs in sorted(by_locale.items()):
        n = len(rs)
        d = 100 * sum(r.dialect["draft_ok"] for r in rs) / n
        f = 100 * sum(r.dialect["final_ok"] for r in rs) / n
        lines.append(f"    {locale:7} {n:>3}  {d:4.0f}%  {f:4.0f}%")
    return lines


def to_json(rows: list[RunScore], perturbations: list[PerturbScore] | None = None,
            alarms: dict[str, int] | None = None) -> str:
    doc: dict[str, Any] = {"runs": [r.to_dict() for r in rows]}
    if perturbations is not None:
        doc["perturbations"] = perturb_to_dicts(perturbations)
        doc["false_alarms"] = alarms or {}
    return json.dumps(doc, ensure_ascii=False, indent=1)


def main_eval(settings: Settings, models: list[str] | None, indexes: list[int] | None,
              out: str | None, sample_set: str = "demo", perturb: bool = False,
              critic_model: str | None = None, report: str | None = None) -> int:
    if sample_set not in SETS:
        print(f"unknown set {sample_set!r}; choose one of {', '.join(SETS)}")
        return 2

    def live(row: RunScore) -> None:
        state = "ERROR" if row.error else ("pass" if row.passed else "fail")
        print(f"  [{row.model}] {row.sample_id} {row.label}: {state} ({row.seconds}s)",
              flush=True)

    def live_p(row: PerturbScore) -> None:
        if not row.applicable:
            return
        how = "neutralized" if row.neutralized else "critic" if row.by_critic \
            else "arbiter" if row.by_arbiter else "MISSED"
        print(f"  [{row.model}] {row.sample_id} {row.mutation}: {how}", flush=True)

    print(f"Envoy eval  set={sample_set}  provider={settings.provider}  "
          f"models={models or ['(configured)']}"
          + (f"  critic={critic_model}" if critic_model else ""))
    rows = asyncio.run(run_eval(settings, models, indexes, on_row=live, sample_set=sample_set,
                                critic_model=critic_model))
    print(render_table(rows))
    perturbations, alarms = None, None
    if perturb:
        print("\nPerturbing every run:")
        perturbations, alarms = asyncio.run(run_perturbations(rows, settings, on_row=live_p))
        print(render_perturb(perturbations, alarms))
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(to_json(rows, perturbations, alarms))
        print(f"\nWrote {out}")
    if report:
        from .report import render

        doc = json.loads(to_json(rows, perturbations, alarms))
        with open(report, "w", encoding="utf-8") as f:
            f.write(render([doc], title=f"Envoy eval: {sample_set} set"))
        print(f"Wrote {report}")
    return 0 if all(r.passed for r in rows) else 1
