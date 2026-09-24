import asyncio
import json

from envoy import db
from envoy.config import Settings
from envoy.demo import seed_demo
from envoy.eval import CHECK_ORDER, INVARIANTS, render_table, run_eval, score, to_json
from envoy.evalset import Sample, load
from envoy.locales import seed_locales
from envoy.models.stub import StubModel
from envoy.pipeline import compose
from envoy.schemas import ComposeRequest
from envoy.tools import DirectTools


def _settings():
    return Settings(provider="stub", user_name="Safea")


def _con():
    con = db.connect()
    seed_locales(con)
    seed_demo(con)
    return con


def test_stub_passes_every_sample_in_every_set():
    rows = asyncio.run(run_eval(_settings(), con=_con(), sample_set="all"))
    assert len(rows) == len(load("all"))
    failing = [(r.sample_id, r.failed_checks, r.error) for r in rows if not r.passed]
    assert failing == [], failing
    assert all(r.invariants == {"greeting": True, "signoff": True} for r in rows)
    table = render_table(rows)
    assert f"stub: {len(rows)}/{len(rows)} passed" in table
    doc = json.loads(to_json(rows))
    assert doc["runs"][0]["passed"] is True and "result" not in doc["runs"][0]


def test_subset_by_index_and_several_model_names():
    rows = asyncio.run(run_eval(_settings(), models=["a", "b"], indexes=[1, 6], con=_con()))
    assert [(r.model, r.sample_id) for r in rows] == [
        ("stub", "demo-01"), ("stub", "demo-06"), ("stub", "demo-01"), ("stub", "demo-06")]


async def _result(message: str):
    con = _con()
    return await compose(ComposeRequest(message=message), settings=_settings(),
                         model=StubModel(), tools=DirectTools(con), con=con)


def test_facts_match_numbers_as_whole_tokens_in_any_script():
    r = asyncio.run(_result("ازيك، امتى بيرجع الاسترداد بتاع طلب #7788؟"))
    good = Sample(id="x", label="x", text="", locale="ar-EG", facts=[["5"]], wrong=["14"])
    checks, invariants = score(r, good, "Safea")
    assert all(checks.values()) and list(checks) == CHECK_ORDER
    assert invariants == {"greeting": True, "signoff": True} and list(invariants) == INVARIANTS
    # "5" is written as ٥ in the reply; a contradiction written either way is caught.
    wrong = Sample(id="x", label="x", text="", locale="ar-EG", facts=[["٥"]], wrong=["٥"])
    assert score(r, wrong, "Safea")[0]["no_wrong"] is False
    # 7788 (the order number) does not satisfy a fact of "78", and "5" is not found in "٥٥".
    assert score(r, Sample(id="x", label="x", text="", locale="ar", facts=[["78"]]),
                 "Safea")[0]["fact"] is False


def test_locale_language_prefix_terms_and_forbidden():
    r = asyncio.run(_result("Hi, what is the warranty on the SkyPack?"))
    s = Sample(id="x", label="x", text="", locale="en", terms=["SkyPack"], forbid=["gift card"])
    assert all(score(r, s, "Safea")[0].values())
    s = Sample(id="x", label="x", text="", locale="fr", terms=["Sky Pack"], forbid=["warranty"])
    c = score(r, s, "Safea")[0]
    assert (c["locale"], c["terms"], c["no_forbidden"]) == (False, False, False)


def test_broken_invariant_is_reported_but_does_not_fail_the_run():
    r = asyncio.run(_result("Hi, what is the warranty on the SkyPack?"))
    r.final_text = "Yo!\n\n" + r.final_text
    s = Sample(id="x", label="x", text="", locale="en")
    checks, invariants = score(r, s, "Safea")
    assert all(checks.values()) and invariants["greeting"] is False


def test_failed_checks_come_with_a_reason_and_the_reader_output(settings, demo_con):
    from envoy.eval import explain

    rows = asyncio.run(run_eval(settings, con=demo_con, sample_set="demo", scorers={}))
    r = rows[0]
    assert r.reading["language"] and "must_preserve" in r.reading
    assert r.details == {} and r.to_dict()["reading"] == r.reading
    sample = load("demo")[0]
    strict = Sample(id=sample.id, label=sample.label, text=sample.text, locale="fr-FR",
                    facts=[["9999"]], wrong=[sample.facts[0][0]], terms=["zzz"],
                    forbid=[sample.facts[0][0]])
    checks, _ = score(r.result, strict, settings.user_name)
    why = explain(r.result, strict, checks)
    assert why["locale"].startswith(f"resolved to {r.locale}, expected fr-FR")
    assert "region_guess" in why["locale"]
    assert why["fact"] == "not in the reply: 9999"
    assert sample.facts[0][0] in why["no_wrong"] and sample.facts[0][0] in why["no_forbidden"]
    assert why["terms"] == "glossary terms missing: zzz"
    assert set(why) == {"locale", "fact", "no_wrong", "terms", "no_forbidden"}
