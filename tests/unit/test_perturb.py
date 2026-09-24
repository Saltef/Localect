import asyncio

from envoy import db
from envoy.config import Settings
from envoy.demo import seed_demo
from envoy.eval import run_eval, run_perturbations
from envoy.locales import seed_locales
from envoy.models.stub import StubModel
from envoy.perturb import MUTATIONS, false_alarms, mutate, perturb_one, render_perturb


def _rows(sample_set="demo"):
    con = db.connect()
    seed_locales(con)
    seed_demo(con)
    settings = Settings(provider="stub", user_name="Safea")
    return settings, asyncio.run(run_eval(settings, con=con, sample_set=sample_set))


def test_every_mutation_changes_exactly_one_segment():
    _, rows = _rows("all")
    # The sizes question quotes "30 litres" and "16 inch" from the message back, so
    # even the must-preserve fault applies here.
    r = next(x for x in rows if x.sample_id == "pt-BR-03").result
    for m in MUTATIONS:
        out = mutate(r, m)
        assert out is not None, m
        rw, seg_id, detail = out
        before = {s.id: s.text for s in r.rewrite.segments}
        after = {s.id: s.text for s in rw.segments}
        changed = [k for k in before if before[k] != after.get(k)]
        assert changed == [seg_id] and detail, m
        assert {s.id: s.text for s in r.rewrite.segments} == before, "the original is untouched"
    # A fault that cannot be planted is reported as such, not as a miss.
    plain = next(x for x in rows if x.sample_id == "demo-03").result
    assert mutate(plain, "drop_preserved") is None


def test_deterministic_layers_catch_what_they_own():
    """The stub Critic knows only must-preserve drift, so these detections are
    the Arbiter's and the pipeline's own: they are the regression gate."""
    settings, rows = _rows("all")
    scores, alarms = asyncio.run(run_perturbations(rows, settings))
    by = {}
    for s in scores:
        if s.applicable:
            by.setdefault(s.mutation, []).append(s)
    assert set(by) == set(MUTATIONS) and len(by["drop_preserved"]) >= 10
    assert all(s.detected and s.neutralized for s in by["wrong_greeting"])
    assert all(s.detected and s.neutralized for s in by["leak_citation"])
    assert all(s.detected and s.by_arbiter for s in by["change_number"])
    assert all(s.detected and s.by_critic for s in by["drop_preserved"])
    assert all(not s.detected for s in by["slang"]), "nothing deterministic can judge register"
    assert alarms == {"runs": len(rows), "critic_block": 0, "arbiter_block": 0,
                      "arbiter_warn": 0}
    table = render_perturb(scores, alarms)
    assert "change_number" in table and "100%" in table and "false alarms on" in table


def test_promise_with_a_number_already_in_the_message_is_not_caught_by_numbers():
    _, rows = _rows()
    r = rows[6].result  # the injection sample mentions $50, so a planted "$50" is covered
    s = asyncio.run(perturb_one(r, "add_promise", StubModel(), "Safea"))
    assert s.applicable and not s.by_arbiter and not s.detected


def test_false_alarms_counts_only_verifier_findings():
    _, rows = _rows()
    fa = false_alarms([(r.sample_id, r.result) for r in rows])
    assert fa["runs"] == len(rows) and fa["critic_block"] == 0
