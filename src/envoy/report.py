"""One markdown report from the JSON that ``envoy eval``, ``envoy bench``
and ``envoy study score`` write. Nothing here runs a model; it renders what
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


def render(docs: list[dict[str, Any]], title: str = "Envoy evaluation report") -> str:
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
