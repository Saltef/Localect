import asyncio

from envoy import db
from envoy.config import Settings
from envoy.demo import SAMPLE_MESSAGES
from envoy.eval import CHECK_ORDER, render_table, run_eval, to_json
from envoy.locales import seed_locales


def test_samples_carry_expectations():
    for s in SAMPLE_MESSAGES:
        assert s["expect_locale"] and (s.get("expect_any") or s.get("expect_all"))
    assert SAMPLE_MESSAGES[6]["forbid"]


def test_eval_on_stub_passes_every_sample():
    con = db.connect()
    seed_locales(con)
    settings = Settings(provider="stub", user_name="Safea")
    rows = asyncio.run(run_eval(settings, con=con))
    assert len(rows) == len(SAMPLE_MESSAGES)
    failing = [(r.index, [k for k in CHECK_ORDER if not r.checks[k]]) for r in rows
               if not r.passed]
    assert failing == [], failing
    table = render_table(rows)
    assert "stub: 7/7 passed" in table and "no_forbidden" not in table
    assert '"passed": true' in to_json(rows)


def test_eval_subset_and_multiple_model_names_on_stub():
    con = db.connect()
    seed_locales(con)
    settings = Settings(provider="stub", user_name="Safea")
    rows = asyncio.run(run_eval(settings, models=["a", "b"], indexes=[1, 6], con=con))
    assert [(r.model, r.index) for r in rows] == [("stub", 1), ("stub", 6), ("stub", 1),
                                                   ("stub", 6)]
