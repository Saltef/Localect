import asyncio
import json

from envoy import db
from envoy.config import Settings
from envoy.demo import seed_demo
from envoy.eval import run_eval, run_perturbations, to_json
from envoy.locales import seed_locales
from envoy.report import load_docs, render


def _eval_doc():
    con = db.connect()
    seed_locales(con)
    seed_demo(con)
    settings = Settings(provider="stub", user_name="Safea")
    rows = asyncio.run(run_eval(settings, con=con, sample_set="demo"))
    perts, alarms = asyncio.run(run_perturbations(rows, settings))
    return json.loads(to_json(rows, perts, alarms))


def test_report_composes_every_section_that_is_present(tmp_path):
    doc = _eval_doc()
    massive = {"massive": [{"model": "stub", "language": "ar", "slots": 2, "slots_strict": 1,
                            "slots_lenient": 2, "language_ok": True, "error": ""}]}
    flores = {"flores": [{"model": "stub", "language": "ar", "hypothesis": "the cat sat",
                          "reference": "the cat sat", "error": ""}]}
    study = {"items_rated": 3, "ratings": 6, "raters": ["a", "b"], "comparisons": {
        "rewrite|ar-EG|final vs draft": {"kind": "rewrite", "locale": "ar-EG",
                                         "pair": "final vs draft", "winner": "final",
                                         "prefer": {"final": 0.75, "draft": 0.25, "tie": 0.0},
                                         "ci95": [0.5, 1.0], "items": 3, "tie_votes": 0,
                                         "alpha": 0.6, "kappa": 0.5,
                                         "conditions": {"final": {"nativeness": 4.5},
                                                        "draft": {"nativeness": 3.0}}}}}
    for name, d in (("e.json", doc), ("m.json", massive), ("f.json", flores), ("s.json", study)):
        (tmp_path / name).write_text(json.dumps(d), encoding="utf-8")
    md = render(load_docs([tmp_path / n for n in ("e.json", "m.json", "f.json", "s.json")]))
    assert md.startswith("# Envoy evaluation report\n")
    for heading in ("### Checks", "### Perturbations", "### Reader on MASSIVE",
                    "### Critic back-translation", "### Human study"):
        assert heading in md, heading
    assert "| stub | 7/7 | 0 | none | 0 |" in md
    assert "| stub | change_number | 7 | 100% | 0% | 100% | 0% |" in md
    assert "| stub | ar | 1 | 0 | 100.0 | ok |" in md
    assert "| rewrite | ar-EG | final vs draft | final 75% | 50-100 | 3 | 0 | 0.60 | 0.50 |" in md
    assert "False alarms on 7 untouched passing runs" in md


def test_report_lists_failures_and_handles_a_bare_list():
    doc = _eval_doc()
    doc["runs"][1]["passed"] = False
    doc["runs"][1]["checks"]["fact"] = False
    md = render([doc])
    assert "Failures:" in md and "| stub | demo-01 | fact |" in md
    assert "| stub | 6/7 |" in md and "fact 1" in md
    assert "Nothing to report" in render([{"runs": []}])
    assert "### Checks" in render([{"runs": doc["runs"]}])
