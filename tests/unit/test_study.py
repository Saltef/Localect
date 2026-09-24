import csv
import json
from pathlib import Path

from envoy.study import (
    bootstrap_ci,
    build_items,
    cohen_kappa,
    export,
    krippendorff_alpha,
    read_sheets,
    render_report,
    score,
)


def _runs():
    body = "Hi there,\n\n{}\n\nBest,\nSafea"
    out = []
    for sid, loc in (("ar-EG-01", "ar-EG"), ("ar-EG-02", "ar-EG"), ("pt-BR-01", "pt-BR")):
        for model in ("m1", "m2"):
            out.append({"model": model, "sample_id": sid, "locale": loc, "message": "msg " + sid,
                        "draft_text": body.format(f"draft {sid}"),
                        "final_text": body.format(f"final {sid} by {model}")})
    out.append({"model": "m1", "sample_id": "same", "locale": "pt-BR", "message": "x",
                "draft_text": body.format("same"), "final_text": body.format("same")})
    return out


def test_items_are_blind_seeded_and_skip_identical_pairs():
    items = build_items(_runs(), seed=1)
    kinds = [it.kind for it in items]
    assert kinds.count("rewrite") == 6 and kinds.count("model") == 3
    assert all(it.left != it.right for it in items)
    assert not any(it.sample_id == "same" for it in items)
    assert all("Hi there" not in it.left and "Safea" not in it.right for it in items), \
        "greeting and sign-off are dropped"
    sides = {(it.left_is, it.right_is) for it in items if it.kind == "rewrite"}
    assert len(sides) == 2, "sides are randomized"
    assert build_items(_runs(), seed=1) == items, "deterministic for a seed"
    assert build_items(_runs(), seed=2) != items


def test_export_writes_one_sheet_per_locale_and_a_key(tmp_path):
    items = build_items(_runs())
    paths = export(items, tmp_path)
    names = sorted(p.name for p in paths)
    assert names == ["key.json", "sheet-ar-EG.csv", "sheet-pt-BR.csv"]
    with (tmp_path / "sheet-ar-EG.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and set(rows[0]) >= {"item", "message", "left", "right", "prefer", "rater"}
    assert all(r["prefer"] == "" for r in rows)
    key = json.loads((tmp_path / "key.json").read_text(encoding="utf-8"))
    assert set(key) == {it.item for it in items}
    assert all(k["left"] != k["right"] for k in key.values())
    assert not any("final" in r["left"] and "draft" in r["left"] for r in rows)


def _fill(tmp_path: Path, rater: str, choose, nativeness):
    """Fill every sheet as one rater who prefers what ``choose`` says."""
    key = json.loads((tmp_path / "key.json").read_text(encoding="utf-8"))
    for sheet in tmp_path.glob("sheet-*.csv"):
        if len(sheet.stem.split(".")) > 1:
            continue
        with sheet.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        out = tmp_path / f"{sheet.stem}.{rater}.csv"
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            for r in rows:
                k = key[r["item"]]
                want = choose(k)
                r["prefer"] = "left" if k["left"] == want else "right" if k["right"] == want \
                    else "tie"
                for side in ("left", "right"):
                    n = nativeness(k[side])
                    r[f"nativeness_{side}"] = str(n)
                    r[f"register_{side}"] = str(n)
                    r[f"facts_{side}"] = "y"
                    r[f"send_{side}"] = "y" if n >= 4 else "n"
                w.writerow(r)


def test_scoring_recovers_a_planted_preference_and_agreement(tmp_path):
    export(build_items(_runs()), tmp_path)
    prefer_final = lambda k: "final" if k["kind"] == "rewrite" else "m2"  # noqa: E731
    nat = lambda cond: 5 if cond in ("final", "m2") else 2  # noqa: E731
    _fill(tmp_path, "mona", prefer_final, nat)
    _fill(tmp_path, "omar", prefer_final, nat)
    assert len(read_sheets(tmp_path)) == 18
    report = score(tmp_path)
    assert report["raters"] == ["mona", "omar"] and report["items_rated"] == 9
    c = report["comparisons"]["rewrite|ar-EG|final vs draft"]
    assert c["items"] == 4 and c["prefer_winner"] == 1.0 and c["ci95"] == [1.0, 1.0]
    assert c["alpha"] == 1.0 and c["kappa"] == 1.0
    assert c["conditions"]["final"]["nativeness"] == 5.0
    assert c["conditions"]["draft"]["send"] == 0.0 and c["conditions"]["final"]["send"] == 1.0
    m = report["comparisons"]["model|pt-BR|m1 vs m2"]
    assert m["winner"] == "m2" and m["prefer_winner"] == 1.0
    text = render_report(report)
    assert "prefer final 100%" in text and "alpha=1.00" in text and "kappa=1.00" in text


def test_disagreement_ties_and_missing_cells(tmp_path):
    export(build_items(_runs()), tmp_path)
    _fill(tmp_path, "a", lambda k: "final" if k["kind"] == "rewrite" else "m2", lambda c: 4)
    _fill(tmp_path, "b", lambda k: "draft" if k["kind"] == "rewrite" else "m1", lambda c: 3)
    # Rater b leaves one row blank and marks another a tie.
    sheet = tmp_path / "sheet-ar-EG.b.csv"
    with sheet.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rows[0]["prefer"] = ""
    rows[0]["nativeness_left"] = ""
    rows[1]["prefer"] = "tie"
    with sheet.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    report = score(tmp_path)
    c = report["comparisons"]["rewrite|ar-EG|final vs draft"]
    assert 0.5 < c["prefer_winner"] < 1.0 and c["tie_votes"] == 1
    assert c["alpha"] is not None and c["alpha"] < 0.5
    assert c["ci95"][0] <= c["prefer_winner"] <= c["ci95"][1]


def test_agreement_statistics_on_known_data():
    assert krippendorff_alpha({"i1": {"a": "x", "b": "x"}, "i2": {"a": "y", "b": "y"}}) == 1.0
    low = krippendorff_alpha({"i1": {"a": "x", "b": "y"}, "i2": {"a": "y", "b": "x"},
                              "i3": {"a": "x", "b": "y"}})
    assert low is not None and low < 0
    assert krippendorff_alpha({"i1": {"a": "x"}}) is None  # a single rating is no agreement
    assert cohen_kappa({"1": "x", "2": "y"}, {"1": "x", "2": "y"}) == 1.0
    assert cohen_kappa({"1": "x", "2": "y", "3": "x", "4": "y"},
                       {"1": "x", "2": "x", "3": "y", "4": "y"}) == 0.0
    assert cohen_kappa({"1": "x"}, {"2": "x"}) is None
    lo, hi = bootstrap_ci([1.0, 0.0, 1.0, 1.0, 0.0, 1.0])
    assert 0.0 <= lo <= 4 / 6 <= hi <= 1.0
