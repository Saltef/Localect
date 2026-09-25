"""envoy bench memory: the fixture mailbox and the numbers it yields on the stub."""

import asyncio

from envoy import db
from envoy.config import Settings
from envoy.evalx.memory import (
    load_mailbox,
    memory_to_dicts,
    render_memory,
    run_memory,
    seed_mailbox,
    summarize,
)
from envoy.report import render


def test_fixture_mailbox_is_consistent():
    box = load_mailbox()
    assert box.me == "safea@example.com"
    ids = {m["id"] for m in box.messages}
    assert len(ids) == len(box.messages) == 19
    assert len(box.questions) == 14 and len({q.id for q in box.questions}) == 14
    for q in box.questions:
        assert q.relevant and set(q.relevant) <= ids, q.id
        assert q.newest or not q.stale, q.id  # a stale value needs a newest one
        assert q.locale and q.text
    changed = [q for q in box.questions if q.stale]
    assert len(changed) == 10 and sum(q.text and 1 for q in box.questions if q.contact) == 5


def test_seed_mailbox_marks_mine_detects_languages_and_is_idempotent():
    con = db.connect()
    box = load_mailbox()
    ids = seed_mailbox(con, box)
    assert len(ids) == 19 and db.message_count(con) == {"messages": 19, "mine": 16}
    assert seed_mailbox(con, box) == ids
    langs = {m["external_id"]: m["language"] for m in db.message_list(con)}
    assert (langs["m09"], langs["m02"], langs["m03"], langs["m13"]) == ("ar", "pt", "de", "ja")


def test_stub_baseline_on_the_fixture_mailbox():
    """The stub's numbers, pinned so a change in retrieval or the Arbiter shows
    up here. The stub's Extractor calls every sentence with a number a fact,
    newsletters included, so its fact numbers are a floor, not a claim."""
    rows = asyncio.run(run_memory(Settings(provider="stub", user_name="Safea")))
    s = summarize(rows)
    assert (s["n"], s["errors"], s["cross_lingual"]) == (14, 0, 7)
    assert s["lexical"] == {1: 9, 3: 12, 5: 13} and s["hybrid"] == {1: 9, 3: 12, 5: 13}
    assert s["lexical_cross"] == {1: 4, 3: 6, 5: 7} and s["hybrid_cross"] == {1: 4, 3: 5, 5: 6}
    assert (s["valued"], s["newest_ok"], s["stale_used"]) == (13, 9, 1)
    assert (s["with_stale"], s["flagged"]) == (10, 4)
    # the hybrid search finds the Japanese answer the token search cannot
    ja = next(r for r in rows if r.question == "mem-10")
    assert ja.lexical_rank == 0 and ja.hybrid_rank == 2
    # a stale fact used by the reply is a block, so the reply escalates
    de = next(r for r in rows if r.question == "mem-03")
    assert de.stale_used and de.flagged and de.status == "escalate" and not de.passed
    ok = next(r for r in rows if r.question == "mem-14")
    assert ok.passed and ok.newest_ok and ok.flagged and ok.status == "check"
    text = render_memory(rows)
    assert "14 questions, 7 cross-lingual, 0 errors" in text
    assert "newest value used 9/13, stale value used 1/13; conflicts flagged 4/10" in text
    md = render([{"memory": memory_to_dicts(rows)}])
    assert "### Memory on the fixture mailbox" in md
    assert "| stub | 14 | 0 | 64% (9/14) / 64% (9/14) |" in md
    assert "| stub | 13 | 69% (9/13) | 8% (1/13) | 10 | 40% (4/10) |" in md
    assert "| stub | 7 | 57% (4/7) / 57% (4/7) |" in md
