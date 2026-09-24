"""The human study: blind pairwise sheets out, agreement and preference in.

No classifier can say whether a reply reads like a native wrote it at the
right register. Native readers can, if the comparison is blind and the
questions are fixed. This module turns finished eval runs into rating
sheets and turns filled sheets back into numbers with uncertainty.

Export: for every run, draft body versus final body (the Rewriter's effect),
and, when two or more models were run on the same sample, model versus
model on the final text. Each item shows the incoming message and two
replies, left and right, in a seeded random order; which is which lives in
a separate key file the raters never see. One CSV per locale so a rater
only sees their own language.

Score: sheets from any number of raters are joined with the key; per
comparison and per locale, the preference rate with a bootstrap 95%
interval, mean nativeness and register per condition, the would-send rate,
and inter-rater agreement (Krippendorff's alpha; Cohen's kappa for exactly
two raters). Missing cells are skipped, not imputed.
"""

from __future__ import annotations

import csv
import json
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COLUMNS = ["item", "locale", "message", "left", "right", "prefer", "nativeness_left",
           "nativeness_right", "register_left", "register_right", "facts_left", "facts_right",
           "send_left", "send_right", "edit", "rater"]
PREFER = {"left", "right", "tie"}
YES = {"y", "yes", "1", "true"}
NO = {"n", "no", "0", "false"}


@dataclass
class Item:
    item: str
    kind: str  # rewrite | model
    sample_id: str
    locale: str
    message: str
    left: str
    right: str
    left_is: str  # "draft" | "final" | a model name
    right_is: str


def _body(text: str) -> str:
    """Drop the greeting and sign-off: code applies them to both sides."""
    parts = [p for p in text.split("\n\n") if p.strip()]
    return "\n\n".join(parts[1:-1]) if len(parts) > 2 else text


def build_items(runs: list[dict[str, Any]], seed: int = 7, bodies_only: bool = True) -> list[Item]:
    """``runs`` are eval rows (model, sample_id, locale, message, draft_text,
    final_text). Returns blinded items in a stable, seeded order."""
    rng = random.Random(seed)
    items: list[Item] = []
    text = _body if bodies_only else (lambda t: t)
    by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        if not r.get("final_text") or r.get("error"):
            continue
        by_sample[r["sample_id"]].append(r)
    for sample_id in sorted(by_sample):
        rs = by_sample[sample_id]
        for r in rs:
            a, b = text(r["draft_text"]), text(r["final_text"])
            if a.strip() == b.strip():
                continue  # nothing to compare
            flip = rng.random() < 0.5
            items.append(Item(item=f"{sample_id}~r{len(items):03d}", kind="rewrite",
                              sample_id=sample_id, locale=r["locale"], message=r["message"],
                              left=b if flip else a, right=a if flip else b,
                              left_is="final" if flip else "draft",
                              right_is="draft" if flip else "final"))
        models = sorted({r["model"] for r in rs})
        for i in range(len(models)):
            for j in range(i + 1, len(models)):
                ra = next(r for r in rs if r["model"] == models[i])
                rb = next(r for r in rs if r["model"] == models[j])
                a, b = text(ra["final_text"]), text(rb["final_text"])
                if a.strip() == b.strip():
                    continue
                flip = rng.random() < 0.5
                items.append(Item(item=f"{sample_id}~m{len(items):03d}", kind="model",
                                  sample_id=sample_id, locale=ra["locale"], message=ra["message"],
                                  left=b if flip else a, right=a if flip else b,
                                  left_is=models[j] if flip else models[i],
                                  right_is=models[i] if flip else models[j]))
    rng.shuffle(items)
    return items


def export(items: list[Item], out_dir: Path) -> list[Path]:
    """One sheet per locale (UTF-8 with BOM so spreadsheets open Arabic and
    Japanese correctly), plus key.json for the scorer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    by_locale: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_locale[it.locale].append(it)
    for locale, its in sorted(by_locale.items()):
        path = out_dir / f"sheet-{locale}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            for it in its:
                w.writerow([it.item, it.locale, it.message, it.left, it.right] + [""] * 11)
        written.append(path)
    key = {it.item: {"kind": it.kind, "sample_id": it.sample_id, "locale": it.locale,
                     "left": it.left_is, "right": it.right_is} for it in items}
    (out_dir / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    written.append(out_dir / "key.json")
    return written


# --- scoring -------------------------------------------------------------------


def _num(v: str) -> float | None:
    try:
        return float(v.strip())
    except (ValueError, AttributeError):
        return None


def _yn(v: str) -> bool | None:
    t = (v or "").strip().lower()
    return True if t in YES else False if t in NO else None


def read_sheets(sheets_dir: Path) -> list[dict[str, str]]:
    """Every filled row from every ``sheet-*.csv`` under the directory. A
    rater is the ``rater`` column, or the file's suffix (``sheet-ar-EG.mona.csv``)."""
    rows = []
    for path in sorted(sheets_dir.glob("sheet-*.csv")):
        parts = path.stem.split(".")
        file_rater = parts[1] if len(parts) > 1 else ""
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                r = {k: (v or "") for k, v in r.items() if k}
                r["rater"] = r.get("rater") or file_rater or "rater"
                if (r.get("prefer") or "").strip().lower() in PREFER or _num(
                        r.get("nativeness_left", "")) is not None:
                    rows.append(r)
    return rows


def krippendorff_alpha(ratings: dict[str, dict[str, str]]) -> float | None:
    """Nominal alpha over units (items) x coders (raters); units with fewer
    than two ratings are ignored, as the method requires."""
    units = [list(v.values()) for v in ratings.values() if len(v) >= 2]
    n = sum(len(u) for u in units)
    if n <= 1:
        return None
    o: Counter = Counter()
    for u in units:
        m = len(u)
        for i, c in enumerate(u):
            for j, k in enumerate(u):
                if i != j:
                    o[(c, k)] += 1 / (m - 1)
    nc: Counter = Counter()
    for (c, _k), v in o.items():
        nc[c] += v
    d_o = sum(v for (c, k), v in o.items() if c != k)
    d_e = sum(nc[c] * nc[k] for c in nc for k in nc if c != k) / (n - 1)
    if d_e == 0:
        return 1.0 if d_o == 0 else None
    return 1 - d_o / d_e


def cohen_kappa(a: dict[str, str], b: dict[str, str]) -> float | None:
    shared = sorted(set(a) & set(b))
    if not shared:
        return None
    n = len(shared)
    agree = sum(a[i] == b[i] for i in shared) / n
    pa, pb = Counter(a[i] for i in shared), Counter(b[i] for i in shared)
    expected = sum(pa[c] * pb[c] for c in set(pa) | set(pb)) / (n * n)
    if expected == 1:
        return 1.0
    return (agree - expected) / (1 - expected)


def bootstrap_ci(values: list[float], n: int = 1000, seed: int = 7) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    return (means[int(0.025 * n)], means[int(0.975 * n) - 1])


def score(sheets_dir: Path) -> dict[str, Any]:
    key = json.loads((sheets_dir / "key.json").read_text(encoding="utf-8"))
    rows = read_sheets(sheets_dir)
    # Resolve every rating to conditions.
    per_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        k = key.get(r["item"])
        if not k:
            continue
        side = {"left": k["left"], "right": k["right"]}
        pref = (r.get("prefer") or "").strip().lower()
        rec = {"rater": r["rater"], "kind": k["kind"], "locale": k["locale"],
               "prefer": side.get(pref, "tie" if pref == "tie" else None)}
        for cond, s in side.items():
            rec[s] = {"nativeness": _num(r.get(f"nativeness_{cond}", "")),
                      "register": _num(r.get(f"register_{cond}", "")),
                      "facts": _yn(r.get(f"facts_{cond}", "")),
                      "send": _yn(r.get(f"send_{cond}", ""))}
        per_item[r["item"]].append(rec)

    out: dict[str, Any] = {"items_rated": len(per_item), "ratings": len(rows),
                           "raters": sorted({r["rater"] for r in rows}), "comparisons": {}}
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)  # (kind, locale, pair)
    for item in per_item:
        k = key[item]
        pair = "final vs draft" if k["kind"] == "rewrite" else " vs ".join(
            sorted([k["left"], k["right"]]))
        groups[(k["kind"], k["locale"], pair)].append(item)
    for (kind, locale, pair), items in sorted(groups.items()):
        winner, loser = (("final", "draft") if kind == "rewrite" else tuple(pair.split(" vs ")))
        # Item-level preference: 1 winner, 0 loser, 0.5 tie, averaged over raters.
        prefs, ties = [], 0
        cond_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        agreement: dict[str, dict[str, str]] = {}
        for item in items:
            votes = []
            for rec in per_item[item]:
                p = rec["prefer"]
                if p is None:
                    continue
                votes.append(1.0 if p == winner else 0.0 if p == loser else 0.5)
                agreement.setdefault(item, {})[rec["rater"]] = p
                for cond in (winner, loser):
                    for metric in ("nativeness", "register"):
                        v = rec.get(cond, {}).get(metric)
                        if v is not None:
                            cond_scores[cond][metric].append(v)
                    for metric in ("facts", "send"):
                        v = rec.get(cond, {}).get(metric)
                        if v is not None:
                            cond_scores[cond][metric].append(1.0 if v else 0.0)
            if votes:
                prefs.append(sum(votes) / len(votes))
                ties += sum(1 for v in votes if v == 0.5)
        rate = sum(prefs) / len(prefs) if prefs else 0.0
        lo, hi = bootstrap_ci(prefs)
        raters = sorted({r for d in agreement.values() for r in d})
        kappa = cohen_kappa(*({i: d[r] for i, d in agreement.items() if r in d} for r in raters)) \
            if len(raters) == 2 else None
        out["comparisons"][f"{kind}|{locale}|{pair}"] = {
            "kind": kind, "locale": locale, "pair": pair, "winner": winner, "items": len(prefs),
            "prefer_winner": round(rate, 3), "ci95": [round(lo, 3), round(hi, 3)],
            "tie_votes": ties, "alpha": krippendorff_alpha(agreement), "kappa": kappa,
            "conditions": {c: {m: round(statistics.fmean(v), 3) for m, v in ms.items() if v}
                           for c, ms in cond_scores.items()},
        }
    return out


def render_report(report: dict[str, Any]) -> str:
    lines = [f"Human study: {report['items_rated']} items rated, {report['ratings']} ratings, "
             f"raters: {', '.join(report['raters']) or '(none)'}"]
    if not report["comparisons"]:
        lines.append("  no filled rows found (fill 'prefer' with left, right or tie)")
    for c in report["comparisons"].values():
        a = c["alpha"]
        k = c["kappa"]
        lines.append(f"\n  {c['kind']:8} {c['locale']:7} {c['pair']}: prefer {c['winner']} "
                     f"{100 * c['prefer_winner']:.0f}% (95% CI {100 * c['ci95'][0]:.0f}-"
                     f"{100 * c['ci95'][1]:.0f}), n={c['items']}, ties={c['tie_votes']}"
                     + (f", alpha={a:.2f}" if a is not None else "")
                     + (f", kappa={k:.2f}" if k is not None else ""))
        for cond, ms in c["conditions"].items():
            parts = [f"{m} {v:.2f}" for m, v in ms.items()]
            lines.append(f"    {cond:24} " + ", ".join(parts))
    return "\n".join(lines)
