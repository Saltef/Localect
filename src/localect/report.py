"""One markdown report from the JSON that ``localect eval``, ``localect bench``
and ``localect study score`` write. Nothing here runs a model; it renders what
was measured, with the counts next to every percentage, so a table can be
pasted into docs/EVAL.md or a pull request as it is."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .eval import CHECK_ORDER, INVARIANTS
from .evalx.flores import FLOOR, chrf_corpus
from .perturb import MUTATIONS


def _pct(k: float, n: float) -> str:
    return f"{100 * k / n:.0f}%" if n else "-"


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def runs_md(runs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        by_model[r["model"]].append(r)
    sets = sorted({r.get("set", "") for r in runs})
    lines.append(f"### Checks ({', '.join(s for s in sets if s)} set"
                 f"{'s' if len(sets) > 1 else ''})")
    lines.append("")
    rows = []
    for model, rs in by_model.items():
        ok = [r for r in rs if not r.get("error")]
        passed = sum(1 for r in rs if r.get("passed"))
        judge = next((r.get("critic_model") for r in rs if r.get("critic_model")), "")
        failed: dict[str, int] = defaultdict(int)
        for r in ok:
            for k in CHECK_ORDER:
                if not r["checks"].get(k, True):
                    failed[k] += 1
        broken = sum(1 for r in ok for k in INVARIANTS if not r.get("invariants", {}).get(k, True))
        rows.append([model + (f" (critic: {judge})" if judge else ""), f"{passed}/{len(rs)}",
                     len(rs) - len(ok),
                     ", ".join(f"{k} {v}" for k, v in sorted(failed.items())) or "none",
                     broken, f"{sum(r.get('seconds', 0) for r in rs):.0f}s"])
    lines += _table(["model", "passed", "errors", "failed checks", "broken invariants", "time"],
                    rows)
    # Per-locale pass rates, when more than one locale is present.
    by_locale: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        by_locale[(r["model"], r.get("locale") or "?")].append(r)
    if len({loc for _m, loc in by_locale}) > 1:
        lines += ["", "Per locale:", ""]
        rows = [[m, loc, f"{sum(1 for r in rs if r.get('passed'))}/{len(rs)}"]
                for (m, loc), rs in sorted(by_locale.items())]
        lines += _table(["model", "locale", "passed"], rows)
    fails = [r for r in runs if not r.get("passed")]
    if fails:
        lines += ["", "Failures:", ""]
        rows = [[r["model"], r["sample_id"], _why(r)] for r in fails]
        lines += _table(["model", "sample", "why"], rows)
    return lines


def _why(r: dict[str, Any]) -> str:
    if r.get("error"):
        text = r["error"]
    else:
        failed = [k for k in CHECK_ORDER if not r["checks"].get(k, True)]
        details = r.get("details") or {}
        parts = [f"{k} ({details[k]})" if details.get(k) else k for k in failed]
        if not parts and r.get("status"):
            parts = [r["status"]] + ["; ".join(r["flags"][:3])] * bool(r.get("flags"))
        text = ", ".join(parts)
    return text.replace("|", "\\|").replace("\n", " ")


def dialect_md(runs: list[dict[str, Any]]) -> list[str]:
    scored = [r for r in runs if r.get("dialect")]
    if not scored:
        return []
    lines = ["### Dialect ablation (draft body vs final body, classified by a judge)", ""]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in scored:
        groups[(r["model"], r["dialect"]["target"])].append(r["dialect"])
    rows = []
    for (model, target), ds in sorted(groups.items()):
        n = len(ds)
        rows.append([model, target, n, _pct(sum(d["draft_ok"] for d in ds), n),
                     _pct(sum(d["final_ok"] for d in ds), n), ds[0]["scorer"]])
    return lines + _table(["model", "locale", "n", "draft", "final", "judge"], rows)


def perturb_md(perturbations: list[dict[str, Any]], alarms: dict[str, Any] | None) -> list[str]:
    if not perturbations:
        return []
    lines = ["### Perturbations (planted faults, who caught them)", ""]
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in perturbations:
        by_model[p["model"]].append(p)
    rows = []
    for model, ps in by_model.items():
        for m in MUTATIONS:
            ms = [p for p in ps if p["mutation"] == m and p["applicable"]]
            n = len(ms)
            rows.append([model, m, n, _pct(sum(p["detected"] for p in ms), n),
                         _pct(sum(p["by_critic"] for p in ms), n),
                         _pct(sum(p["by_arbiter"] for p in ms), n),
                         _pct(sum(p["neutralized"] for p in ms), n)])
    lines += _table(["model", "fault", "n", "caught", "critic", "arbiter", "neutralized"], rows)
    if alarms and alarms.get("runs"):
        lines += ["", f"False alarms on {alarms['runs']} untouched passing runs: critic blocked "
                  f"{alarms['critic_block']}, arbiter blocked {alarms['arbiter_block']}, "
                  f"arbiter warned {alarms['arbiter_warn']}."]
    return lines


def massive_md(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = ["### Reader on MASSIVE", ""]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["language"])].append(r)
    out = []
    for (model, lang), rs in sorted(groups.items()):
        ok = [r for r in rs if not r.get("error")]
        slots = sum(r["slots"] for r in ok)
        out.append([model, lang, len(rs), len(rs) - len(ok),
                    _pct(sum(r["language_ok"] for r in ok), len(ok)), slots,
                    _pct(sum(r["slots_strict"] for r in ok), slots),
                    _pct(sum(r["slots_lenient"] for r in ok), slots)])
    return lines + _table(["model", "lang", "n", "errors", "language", "slots", "strict",
                           "lenient"], out)


def flores_md(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = ["### Critic back-translation on FLORES-200 (chrF vs English reference)", ""]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["language"])].append(r)
    out = []
    for (model, lang), rs in sorted(groups.items()):
        ok = [r for r in rs if not r.get("error")]
        score = chrf_corpus([(r["hypothesis"], r["reference"]) for r in ok]) if ok else 0.0
        out.append([model, lang, len(rs), len(rs) - len(ok), f"{score:.1f}",
                    "ok" if ok and score >= FLOOR else f"LOW (below {FLOOR:.0f})"])
    return lines + _table(["model", "lang", "n", "errors", "chrF", "trust"], out)


def memory_md(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    from .evalx.memory import KS, summarize

    lines = ["### Memory on the fixture mailbox (retrieval, newest fact, conflicts)", ""]
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)

    def pc(k: int, n: int) -> str:
        return f"{_pct(k, n)} ({k}/{n})" if n else "-"

    out, out_cross, out_facts = [], [], []
    for model, rs in by_model.items():
        s = summarize(rs)
        out.append([model, s["n"], s["errors"]]
                   + [f"{pc(s['lexical'][k], s['n'])} / {pc(s['hybrid'][k], s['n'])}"
                      for k in KS])
        if s["cross_lingual"]:
            c = s["cross_lingual"]
            out_cross.append([model, c] + [f"{pc(s['lexical_cross'][k], c)} / "
                                           f"{pc(s['hybrid_cross'][k], c)}" for k in KS])
        out_facts.append([model, s["valued"], pc(s["newest_ok"], s["valued"]),
                          pc(s["stale_used"], s["valued"]), s["with_stale"],
                          pc(s["flagged"], s["with_stale"])])
    lines += ["Retrieval, first relevant message in the top k (token search / hybrid):", ""]
    lines += _table(["model", "n", "errors", "@1", "@3", "@5"], out)
    if out_cross:
        lines += ["", "Cross-lingual questions only (the answer was said in another language):",
                  ""]
        lines += _table(["model", "n", "@1", "@3", "@5"], out_cross)
    lines += ["", "Facts in the reply, after extraction by the model:", ""]
    lines += _table(["model", "questions with a value", "newest used", "stale used",
                     "with an older statement", "conflict flagged"], out_facts)
    return lines


def replay_md(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    from .evalx.replay import summarize

    lines = ["### Replay of your own inbox (memory limited to what predated each message)", ""]
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    out = []
    for model, rs in by_model.items():
        s = summarize(rs)
        n_ok = s["n"] - s["errors"]
        out.append([model, s["n"], s["errors"],
                    f"{_pct(s['language_ok'], n_ok)} ({s['language_ok']}/{n_ok})",
                    f"{_pct(s['numbers_hit'], s['numbers_ref'])} "
                    f"({s['numbers_hit']}/{s['numbers_ref']})", s["numbers_extra"],
                    s["chrf_mean"], f"{s['ready']} / {s['check']} / {s['escalate']}",
                    f"{s['with_sources']}/{n_ok}"])
    lines += _table(["model", "exchanges", "errors", "same language", "your numbers stated",
                     "extra numbers", "mean chrF", "ready / check / escalate",
                     "used sources"], out)
    lines += ["", "Each exchange is a real incoming message and the reply you actually sent; "
              "Localect composed with memory cut off at the message's date. chrF compares "
              "Localect's reply with yours (100 = identical)."]
    return lines


def banking_md(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    from .evalx.banking import summarize

    def fr(pair):
        k, n = pair
        return f"{_pct(k, n)} ({k}/{n})" if n else "-"

    lines = ["### Real bank customers on the bank knowledge base (Banking77, ArBanking77, "
             "WolBanking77)", ""]
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(r)
    body = []
    for model, rs in by_model.items():
        for v, d in summarize(rs).items():
            body.append([model, v, d["n"], fr(d["reply_language"]), fr(d["region"]),
                         fr(d["fact"]), fr(d["grounded"]), fr(d["escalate"]), d["locales"]])
    lines += _table(["model", "variety", "n", "reply in language", "region guessed",
                     "fact stated (covered)", "no invented number", "escalated", "resolved to"],
                    body)
    lines += ["", "Real customer queries, hand-localized into Arabic varieties and French. A "
                  "covered intent must state the bank's number; every reply must state no "
                  "number from outside the query and the knowledge base. Region: Saudi "
                  "queries should resolve to ar-SA, Palestinian to ar-LB."]
    return lines


def health_md(grounded: list[dict[str, Any]], patients: list[dict[str, Any]]) -> list[str]:
    if not grounded and not patients:
        return []
    from .evalx.health import summarize_grounded, summarize_patients

    def fr(pair):
        k, n = pair
        return f"{_pct(k, n)} ({k}/{n})" if n else "-"

    lines = []
    if grounded:
        lines += ["### MedlinePlus: grounded replies across languages", ""]
        by_model: dict[str, list[dict[str, Any]]] = {}
        for r in grounded:
            by_model.setdefault(r["model"], []).append(r)
        body = []
        for model, rs in by_model.items():
            s = summarize_grounded(rs)
            body.append([model, s["n"], fr(s["reply_language"]), fr(s["retrieved"]),
                         fr(s["off_topic"]), fr(s["grounded"]), s["chrf_mean"], fr(s["escalate"])])
        lines += _table(["model", "n", "reply in language", "cited the paired topic",
                         "cited a distractor", "no invented number", "mean chrF vs human summary",
                         "escalated"], body)
        lines += ["", "The English (or Spanish) summary of a MedlinePlus topic is the source; "
                      "the question is in the other language; chrF compares the reply with "
                      "the human-written summary in the reply's own language.", ""]
    if patients:
        lines += ["### Real patients against the clinic knowledge base (AraMed, MedPT, LiveQA)",
                  ""]
        by_model = {}
        for r in patients:
            by_model.setdefault(r["model"], []).append(r)
        body = []
        for model, rs in by_model.items():
            for src, d in summarize_patients(rs).items():
                body.append([model, src, d["language"], d["n"], fr(d["reply_language"]),
                             fr(d["grounded"]), fr(d["no_medication"]), fr(d["safe"]),
                             fr(d["ready"]), fr(d["escalate"])])
        lines += _table(["model", "source", "lang", "n", "reply in language",
                         "no invented number", "no medication introduced", "safe", "ready",
                         "escalated"], body)
        lines += ["", "The clinic knowledge base does not answer these questions, so the test "
                      "is that Localect does not play doctor: no number from outside the message "
                      "and the clinic's text, no medication the patient did not name."]
    return lines


def study_md(report: dict[str, Any]) -> list[str]:
    comps = report.get("comparisons") or {}
    if not comps:
        return []
    lines = [f"### Human study ({report.get('items_rated', 0)} items, "
             f"{report.get('ratings', 0)} ratings, raters: "
             f"{', '.join(report.get('raters', [])) or 'none'})", ""]
    rows = []
    for c in comps.values():
        w = c["winner"]
        alpha = c.get("alpha")
        kappa = c.get("kappa")
        nat = {k: v.get("nativeness") for k, v in c.get("conditions", {}).items()}
        rows.append([c["kind"], c["locale"], c["pair"], f"{w} {100 * c['prefer'][w]:.0f}%",
                     f"{100 * c['ci95'][0]:.0f}-{100 * c['ci95'][1]:.0f}", c["items"],
                     c["tie_votes"], f"{alpha:.2f}" if alpha is not None else "-",
                     f"{kappa:.2f}" if kappa is not None else "-",
                     ", ".join(f"{k} {v:.2f}" for k, v in nat.items() if v is not None)])
    return lines + _table(["kind", "locale", "pair", "preferred", "95% CI", "items", "ties",
                           "alpha", "kappa", "nativeness"], rows)


def render(docs: list[dict[str, Any]], title: str = "Localect evaluation report") -> str:
    """Compose every section present in the given JSON documents."""
    lines = [f"# {title}", ""]
    runs = [r for d in docs for r in d.get("runs", [])]
    if runs:
        lines += runs_md(runs) + [""]
        d = dialect_md(runs)
        if d:
            lines += d + [""]
    perturbations = [p for d in docs for p in d.get("perturbations", [])]
    alarms = next((d.get("false_alarms") for d in docs if d.get("false_alarms")), None)
    p = perturb_md(perturbations, alarms)
    if p:
        lines += p + [""]
    m = massive_md([r for d in docs for r in d.get("massive", [])])
    if m:
        lines += m + [""]
    f = flores_md([r for d in docs for r in d.get("flores", [])])
    if f:
        lines += f + [""]
    mem = memory_md([r for d in docs for r in d.get("memory", [])])
    if mem:
        lines += mem + [""]
    rp = replay_md([r for d in docs for r in d.get("replay", [])])
    if rp:
        lines += rp + [""]
    bk = banking_md([r for d in docs for r in d.get("banking", [])])
    if bk:
        lines += bk + [""]
    hl = health_md([r for d in docs for r in d.get("health_grounded", [])],
                   [r for d in docs for r in d.get("health_patients", [])])
    if hl:
        lines += hl + [""]
    for d in docs:
        if "comparisons" in d:
            s = study_md(d)
            if s:
                lines += s + [""]
    if len(lines) == 2:
        lines.append("Nothing to report: the files carried no runs, perturbations, "
                     "benchmarks or study scores.")
    return "\n".join(lines).rstrip() + "\n"


def load_docs(paths: list[str | Path]) -> list[dict[str, Any]]:
    docs = []
    for p in paths:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        docs.append({"runs": doc} if isinstance(doc, list) else doc)
    return docs
