"""Read an experiment folder and say what to change.

Every rule here is a count over stored rows, attributed to the stage that
produced the failure and paired with the lever that changes that stage: a
prompt file, a setting, or a code path. Nothing is inferred from a model's
prose; a finding is a number, its denominator, and a place to look. The
ranking puts grounding and safety first (an invented number, an obeyed
instruction, a medication named), then correctness (a fact omitted, an
item lost), then the verifier's cost (escalations on correct replies),
then the Reader, then efficiency (a stage that does not earn its call).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import banking, health, memory, replay

LEVERS = {
    "reader": "src/localect/prompts/reader.md (language and region cues), locales.yaml notes",
    "drafter": "src/localect/prompts/drafter.md (grounding rules), the knowledge base wording",
    "rewriter": "src/localect/prompts/rewriter.md, the locale profile's notes and voice examples",
    "critic": "src/localect/prompts/critic.md (what drift is), or role_models.critic (another "
              "judge)",
    "arbiter": "src/localect/agents/arbiter.py (deterministic checks)",
    "memory": "the source policy in pipeline.compose (facts, mail paragraphs, voice) and "
              "embed_model",
    "pipeline": "the revision loop in pipeline.compose",
    "adapter": "src/localect/models/* (schema and retry handling)",
}


@dataclass
class Finding:
    stage: str
    title: str
    evidence: str
    lever: str
    count: int = 0
    n: int = 0
    weight: int = 0  # ranking group: lower first
    rows: list[str] = field(default_factory=list)  # example ids

    @property
    def share(self) -> float:
        return self.count / self.n if self.n else 0.0


def _runs(found: dict, cond: str, section: str) -> list[dict[str, Any]]:
    return list(found.get(cond, {}).get(section, {}).get("runs", []))


def _perturbs(found: dict, cond: str, section: str) -> list[dict[str, Any]]:
    return [p for p in found.get(cond, {}).get(section, {}).get("perturbations", [])
            if p.get("applicable")]


def _alarms(found: dict, cond: str, section: str) -> dict[str, Any]:
    return found.get(cond, {}).get(section, {}).get("false_alarms") or {}


def _lang(sample_id: str) -> str:
    return sample_id.split("-")[0] if "-" in sample_id else sample_id


def _by(items: list[str]) -> str:
    c = Counter(items)
    return ", ".join(f"{k} {v}" for k, v in c.most_common(6))


def diagnose(found: dict[str, dict[str, dict[str, Any]]]) -> list[Finding]:
    out: list[Finding] = []
    base_sets = ["heldout", "domains", "injection"]
    base_runs = [r for s in base_sets for r in _runs(found, "base", s)]
    ok = [r for r in base_runs if not r.get("error")]

    # ---- grounding and safety (weight 0)
    forbid = [r for r in ok if not r.get("checks", {}).get("no_forbidden", True)]
    if forbid:
        kinds = [r.get("label", "").split(", ")[-1] for r in forbid]
        out.append(Finding("drafter", "The reply states what the message told it to",
                           f"{len(forbid)}/{len(ok)} replies state a forbidden phrase; by attack: "
                           f"{_by(kinds)}; by language: "
                           f"{_by(_lang(r['sample_id']) for r in forbid)}",
                           LEVERS["drafter"] + "; the Arbiter's echoed_instruction check catches "
                           "verbatim repeats, a paraphrase needs the Drafter",
                           len(forbid), len(ok), 0, [r["sample_id"] for r in forbid[:6]]))
    wrong = [r for r in ok if not r.get("checks", {}).get("no_wrong", True)]
    if wrong:
        out.append(Finding("drafter", "The reply states a value the knowledge base contradicts",
                           f"{len(wrong)}/{len(ok)} replies; "
                           f"{_by(_lang(r['sample_id']) for r in wrong)}",
                           LEVERS["drafter"], len(wrong), len(ok), 0,
                           [r["sample_id"] for r in wrong[:6]]))
    bank = found.get("base", {}).get("banking", {}).get("banking", [])
    if bank:
        inv = [r for r in bank if not r.get("error") and r.get("invented")]
        n = sum(1 for r in bank if not r.get("error"))
        if inv:
            out.append(Finding("drafter", "Real bank customers get numbers the bank never stated",
                               f"{len(inv)}/{n} replies carry a number from outside the query and "
                               f"the knowledge base; by variety: {_by(r['variety'] for r in inv)}; "
                               f"by intent: {_by(r['intent'] for r in inv)}",
                               LEVERS["drafter"], len(inv), n, 0, [r["id"] for r in inv[:6]]))
    pats = found.get("base", {}).get("health", {}).get("health_patients", [])
    if pats:
        meds = [r for r in pats if not r.get("error") and r.get("medications")]
        n = sum(1 for r in pats if not r.get("error"))
        if meds:
            out.append(Finding("drafter", "Replies to real patients name a medication",
                               f"{len(meds)}/{n} replies introduce a medication or a dose the "
                               f"patient did not mention; by source: "
                               f"{_by(r['source'] for r in meds)}",
                               LEVERS["drafter"] + " (a rule that the clinic never names a "
                               "medicine by message)", len(meds), n, 0,
                               [r["id"] for r in meds[:6]]))
        unsafe_nums = [r for r in pats if not r.get("error") and r.get("invented")]
        if unsafe_nums:
            out.append(Finding("drafter", "Replies to real patients state numbers from nowhere",
                               f"{len(unsafe_nums)}/{n} replies; by source: "
                               f"{_by(r['source'] for r in unsafe_nums)}",
                               LEVERS["drafter"], len(unsafe_nums), n, 0,
                               [r["id"] for r in unsafe_nums[:6]]))
    rp = found.get("base", {}).get("replay", {}).get("replay", [])
    if rp:
        s = replay.summarize(rp)
        if s["numbers_extra"]:
            out.append(Finding("drafter", "Replies to your real mail add numbers you never wrote",
                               f"{s['numbers_extra']} extra numbers over {s['n'] - s['errors']} "
                               f"replies (the sent replies' own numbers were hit "
                               f"{s['numbers_hit']}/{s['numbers_ref']})",
                               LEVERS["drafter"] + "; check which sources the extra numbers came "
                               "from with the Sources view", s["numbers_extra"],
                               s["n"] - s["errors"], 0))

    # ---- correctness (weight 1)
    fact = [r for r in ok if not r.get("checks", {}).get("fact", True)]
    if fact:
        out.append(Finding("drafter", "The reply leaves out the knowledge base's number",
                           f"{len(fact)}/{len(ok)} replies miss a required fact; by set: "
                           f"{_by(r.get('set', '') for r in fact)}; by language: "
                           f"{_by(_lang(r['sample_id']) for r in fact)}; statuses: "
                           f"{_by(r.get('status', '') for r in fact)}",
                           LEVERS["drafter"] + "; if the right paragraph was not among the "
                           "sources, the search (alias table, embeddings) is the lever",
                           len(fact), len(ok), 1, [r["sample_id"] for r in fact[:6]]))
    lost = [r for r in ok if not r.get("checks", {}).get("preserved", True)]
    if lost:
        out.append(Finding("rewriter", "The rewrite drops something the draft kept",
                           f"{len(lost)}/{len(ok)} replies lose a must-preserve item; "
                           f"{_by(_lang(r['sample_id']) for r in lost)}",
                           LEVERS["rewriter"], len(lost), len(ok), 1,
                           [r["sample_id"] for r in lost[:6]]))
    terms = [r for r in ok if not r.get("checks", {}).get("terms", True)]
    if terms:
        out.append(Finding("rewriter", "A glossary term does not survive",
                           f"{len(terms)}/{len(ok)} replies; "
                           f"{_by(_lang(r['sample_id']) for r in terms)}",
                           LEVERS["rewriter"], len(terms), len(ok), 1,
                           [r["sample_id"] for r in terms[:6]]))
    if bank:
        cov = [r for r in bank if not r.get("error") and r.get("covered")]
        miss = [r for r in cov if r.get("fact_ok") is False]
        if miss:
            out.append(Finding("drafter", "Real bank customers with a covered question do not "
                               "get the bank's number",
                               f"{len(miss)}/{len(cov)} covered queries; by variety: "
                               f"{_by(r['variety'] for r in miss)}",
                               LEVERS["drafter"] + "; for Arabic and French the alias table in "
                               "text.py decides whether the paragraph is found at all",
                               len(miss), len(cov), 1, [r["id"] for r in miss[:6]]))
    errors = [r for r in base_runs if r.get("error")]
    stage = [r for r in ok if not r.get("checks", {}).get("verified", True)]
    if errors or stage:
        out.append(Finding("adapter", "Stages fail outright",
                           f"{len(errors)} runs errored and {len(stage)} finished with a stage "
                           f"error over {len(base_runs)} runs; "
                           f"{_by((r.get('error') or 'stage error')[:40] for r in errors + stage)}",
                           LEVERS["adapter"], len(errors) + len(stage), len(base_runs), 1,
                           [r["sample_id"] for r in (errors + stage)[:6]]))

    # ---- the verifier's cost and worth (weight 2)
    overblock = [r for r in ok if r.get("status") == "escalate"
                 and all(r.get("checks", {}).values())]
    if overblock:
        kinds = [f.split(":")[1] for r in overblock for f in r.get("flags", [])
                 if ":block " in f]
        out.append(Finding("critic", "Correct replies are escalated",
                           f"{len(overblock)}/{len(ok)} replies pass every check and still "
                           f"escalate; blocking flag kinds: {_by(kinds)}; by language: "
                           f"{_by(_lang(r['sample_id']) for r in overblock)}",
                           LEVERS["critic"], len(overblock), len(ok), 2,
                           [r["sample_id"] for r in overblock[:6]]))
    for section in ("heldout", "domains"):
        al = _alarms(found, "base", section)
        if al.get("critic_block"):
            out.append(Finding("critic", f"The Critic blocks untouched replies ({section})",
                               f"{al['critic_block']}/{al.get('runs', 0)} untouched runs got a "
                               f"Critic block in the perturbation false-alarm pass",
                               LEVERS["critic"], al["critic_block"], al.get("runs", 0), 2))
    if "no_critic" in found:
        for section in ("heldout", "domains"):
            bp, np_ = _perturbs(found, "base", section), _perturbs(found, "no_critic", section)
            if not bp or not np_:
                continue
            caught_base = sum(1 for p in bp if p.get("detected"))
            caught_nc = sum(1 for p in np_ if p.get("detected"))
            critic_only = sum(1 for p in bp if p.get("by_critic") and not p.get("by_arbiter")
                              and not p.get("neutralized"))
            br, nr = _runs(found, "base", section), _runs(found, "no_critic", section)
            pb, pn = (sum(1 for r in br if r.get("passed")), sum(1 for r in nr if r.get("passed")))
            verdict = ("earns its call" if caught_base > caught_nc else "catches nothing code "
                       "does not")
            out.append(Finding("critic", f"What the Critic model adds ({section})",
                               f"faults caught with the Critic {caught_base}/{len(bp)}, without "
                               f"it {caught_nc}/{len(np_)} ({critic_only} caught by the Critic "
                               f"alone); "
                               f"samples passed with it {pb}/{len(br)}, without it {pn}/{len(nr)}: "
                               f"the Critic {verdict}"
                               + ("; it costs passes, see the escalation finding"
                                  if pn > pb else ""),
                               LEVERS["critic"], abs(pb - pn), len(br), 2 if pn > pb else 5))

    # ---- the Reader (weight 3)
    loc = [r for r in ok if not r.get("checks", {}).get("locale", True)]
    region = [r for r in loc if (r.get("reading") or {}).get("language", "")
              == _lang(r["sample_id"]).split("-")[0]]
    langm = [r for r in loc if r not in region]
    if region:
        out.append(Finding("reader", "The Reader gets the language but not the region",
                           f"{len(region)}/{len(ok)} replies resolve to the wrong variety; "
                           f"expected: {_by(r['sample_id'].rsplit('-', 1)[0] for r in region)}; "
                           f"resolved to: {_by(r.get('locale', '') for r in region)}",
                           LEVERS["reader"], len(region), len(ok), 3,
                           [r["sample_id"] for r in region[:6]]))
    if langm:
        out.append(Finding("reader", "The Reader misreads the language",
                           f"{len(langm)}/{len(ok)} replies; expected: "
                           f"{_by(_lang(r['sample_id']) for r in langm)}; read as: "
                           f"{_by((r.get('reading') or {}).get('language', '') for r in langm)}",
                           LEVERS["reader"], len(langm), len(ok), 3,
                           [r["sample_id"] for r in langm[:6]]))
    if bank:
        s = banking.summarize(bank)
        for v, d in s.items():
            k, n = d["region"]
            if n and k < n:
                out.append(Finding("reader", f"Real {v} customers are not read as their region",
                                   f"{k}/{n} resolved to the expected profile; resolved to: "
                                   f"{d['locales']}", LEVERS["reader"], n - k, n, 3))
            k2, n2 = d["reply_language"]
            if n2 and k2 < n2:
                out.append(Finding("rewriter",
                                   f"Replies to {v} customers are not in their language",
                                   f"{k2}/{n2} read as the customer's language",
                                   LEVERS["rewriter"], n2 - k2, n2, 1))
    grounded = found.get("base", {}).get("health", {}).get("health_grounded", [])
    if grounded:
        s = health.summarize_grounded(grounded)
        k, n = s["retrieved"]
        if n and k < n:
            out.append(Finding("memory", "Cross-lingual questions do not reach the paired topic",
                               f"cited the paired MedlinePlus topic {k}/{n}; cited a distractor "
                               f"{s['off_topic'][0]}/{n}",
                               LEVERS["memory"] + "; the Reader's gloss is the query, so "
                               "reader.md matters here too", n - k, n, 3))

    # ---- efficiency: what a stage or a policy earns (weight 4)
    if "no_revision" in found:
        for section in ("heldout", "injection"):
            br, nr = _runs(found, "base", section), _runs(found, "no_revision", section)
            if not br or not nr:
                continue
            pb, pn = (sum(1 for r in br if r.get("passed")), sum(1 for r in nr if r.get("passed")))
            revised = sum(1 for r in br if r.get("revisions"))
            out.append(Finding("pipeline", f"What the revision loop earns ({section})",
                               f"passed with the loop {pb}/{len(br)}, without it {pn}/{len(nr)}; "
                               f"the loop ran on {revised} replies"
                               + ("; it does not pay for its second call" if pb <= pn else ""),
                               LEVERS["pipeline"], abs(pb - pn), len(br), 4))
    if "no_rewriter" in found:
        for section in ("heldout", "domains"):
            br, nr = _runs(found, "base", section), _runs(found, "no_rewriter", section)
            bd = [r for r in br if r.get("dialect")]
            nd = [r for r in nr if r.get("dialect")]
            if bd and nd:
                fb = sum(1 for r in bd if r["dialect"].get("final_ok"))
                fn = sum(1 for r in nd if r["dialect"].get("final_ok"))
                out.append(Finding("rewriter", f"What the Rewriter earns in dialect ({section})",
                                   f"final text in the target variety with the Rewriter "
                                   f"{fb}/{len(bd)}, without it {fn}/{len(nd)}"
                                   + ("; the Rewriter is not moving the dialect" if fb <= fn
                                      else ""), LEVERS["rewriter"], abs(fb - fn), len(bd), 4))
            pb, pn = (sum(1 for r in br if r.get("passed")), sum(1 for r in nr if r.get("passed")))
            if br and nr and pn > pb:
                out.append(Finding("rewriter", f"The Rewriter costs passes ({section})",
                                   f"passed with it {pb}/{len(br)}, without it {pn}/{len(nr)}",
                                   LEVERS["rewriter"], pn - pb, len(br), 1))
    mem_conds = {c: memory.summarize(found[c]["memory"]["memory"]) for c in found
                 if "memory" in found[c] and found[c]["memory"].get("memory")}
    if "base" in mem_conds:
        b = mem_conds["base"]
        lex1, hyb1 = b["lexical"].get(1, 0), b["hybrid"].get(1, 0)
        if hyb1 <= lex1:
            out.append(Finding("memory", "Embeddings do not beat the token search on this mailbox",
                               f"first relevant message at rank 1: lexical {lex1}/{b['n']}, hybrid "
                               f"{hyb1}/{b['n']}", LEVERS["memory"] + " (embed_model)", 0, b["n"],
                               4))
        for c in ("facts_only", "no_facts"):
            if c in mem_conds:
                o = mem_conds[c]
                better = (o["newest_ok"] >= b["newest_ok"] and o["stale_used"] <= b["stale_used"])
                out.append(Finding("memory", f"Source policy: {c} against base",
                                   f"newest value used base {b['newest_ok']}/{b['valued']}, {c} "
                                   f"{o['newest_ok']}/{o['valued']}; stale value used base "
                                   f"{b['stale_used']}/{b['valued']}, {c} "
                                   f"{o['stale_used']}/{o['valued']}; hybrid@1 base "
                                   f"{hyb1}/{b['n']}, {c} {o['hybrid'].get(1, 0)}/{o['n']}"
                                   + (f"; {c} is at least as good: consider it as the default"
                                      if better else ""), LEVERS["memory"],
                                   abs(o["newest_ok"] - b["newest_ok"]), b["valued"], 4))
    rp_conds = {c: replay.summarize(found[c]["replay"]["replay"]) for c in found
                if "replay" in found[c] and found[c]["replay"].get("replay")}
    if "base" in rp_conds:
        b = rp_conds["base"]
        for c in ("no_voice", "facts_only", "no_facts"):
            if c in rp_conds:
                o = rp_conds[c]
                out.append(Finding("memory", f"Replay: {c} against base",
                                   f"chrF base {b['chrf_mean']}, {c} {o['chrf_mean']}; numbers hit "
                                   f"base {b['numbers_hit']}/{b['numbers_ref']}, {c} "
                                   f"{o['numbers_hit']}/{o['numbers_ref']}; extra numbers base "
                                   f"{b['numbers_extra']}, {c} {o['numbers_extra']}",
                                   LEVERS["memory"], 0, b["n"], 4))

    out.sort(key=lambda f: (f.weight, -f.share, -f.count))
    return out


def render_findings(findings: list[Finding]) -> str:
    lines = ["# Findings: what the experiment says to change", ""]
    if not findings:
        lines.append("Nothing to report: every stored row passed and no condition differed.")
        return "\n".join(lines) + "\n"
    lines.append("Ranked: grounding and safety first, then correctness, then what the "
                 "verifier costs, then the Reader, then what each stage or policy earns. "
                 "Each finding is a count with its denominator and the lever that changes "
                 "that stage. Change one lever, rerun the section it names, compare.")
    lines.append("")
    for i, f in enumerate(findings, 1):
        lines.append(f"{i}. **{f.stage}: {f.title}.** {f.evidence}.")
        if f.rows:
            lines.append(f"   Examples: {', '.join(f.rows)} (`localect explain` prints them).")
        lines.append(f"   Lever: {f.lever}.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
