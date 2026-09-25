"""Replaying the user's own inbox, with memory cut off at each message's date."""

import asyncio
import json
from argparse import Namespace
from pathlib import Path

from envoy import db
from envoy.config import Settings
from envoy.evalx.memory import load_mailbox, seed_mailbox
from envoy.evalx.replay import find_pairs, render_replay, replay_to_dicts, run_replay, summarize
from envoy.locales import seed_locales
from envoy.memory import import_paths
from envoy.memory.embed import HashEmbedder
from envoy.memory.facts import extract_pending
from envoy.memory.search import mail_search
from envoy.models.stub import StubModel
from envoy.report import render

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mail"


def _con():
    con = db.connect()
    seed_locales(con)
    return con


def test_pairs_are_incoming_then_your_reply_in_thread_or_to_the_sender():
    con = _con()
    import_paths(con, [FIX / "sample.mbox"], my_addresses=["safea@example.com"])
    pairs = find_pairs(con)
    # Omar's question answered in its thread; Layla's follow-up answered by the
    # later note to her address (no thread id, eight days apart)
    assert [(p.incoming["from_addr"], p.reply["subject"]) for p in pairs] == [
        ("omar@example.org", "Re: الشحن إلى الإسكندرية"),
        ("layla@shop.example", "Return window update")]
    assert all(p.reply["is_mine"] and p.reply["date"] > p.incoming["date"] for p in pairs)
    # the bench mailbox: Layla's and Omar's notes have no reply after them
    con2 = _con()
    seed_mailbox(con2, load_mailbox())
    assert find_pairs(con2) == []
    # a reply to the sender without a thread id counts, but not one two weeks later
    a = db.message_add(con2, text="Can I return it?", from_addr="x@y.example",
                       to_addrs="safea@example.com", date="2026-03-01T10:00:00Z")
    db.message_add(con2, text="Yes, within 30 days.", from_addr="safea@example.com",
                   to_addrs="x@y.example", is_mine=True, date="2026-03-02T10:00:00Z")
    b = db.message_add(con2, text="And the warranty?", from_addr="x@y.example",
                       to_addrs="safea@example.com", date="2026-04-01T10:00:00Z")
    db.message_add(con2, text="Two years.", from_addr="safea@example.com",
                   to_addrs="x@y.example", is_mine=True, date="2026-04-20T10:00:00Z")
    pairs = find_pairs(con2)
    assert [p.incoming["id"] for p in pairs] == [a]
    assert find_pairs(con2, contact="nobody@y.example") == []
    assert b not in {p.incoming["id"] for p in find_pairs(con2, since="2026-03-15")}


def test_memory_is_cut_off_at_the_incoming_date():
    con = _con()
    import_paths(con, [FIX / "sample.mbox"], my_addresses=["safea@example.com"])
    asyncio.run(extract_pending(con, StubModel()))
    pair = next(p for p in find_pairs(con) if p.incoming["from_addr"] == "omar@example.org")
    when = pair.incoming["date"]
    later = mail_search(con, HashEmbedder(), "الشحن للإسكندرية")
    assert any("٣ لـ ٥" in h["text"] for h in later), "without a cutoff the answer is found"
    cut = mail_search(con, HashEmbedder(), "الشحن للإسكندرية", before=when)
    assert all("٣ لـ ٥" not in h["text"] for h in cut), "with the cutoff it is not"
    assert all(f["said_on"] < when for f in db.facts_search(con, "shipping", before=when))
    assert all(v["date"] < when for v in db.voice_examples(con, "ar", before=when))


def test_replay_scores_and_reports_on_the_stub():
    con = _con()
    import_paths(con, [FIX / "sample.mbox"], my_addresses=["safea@example.com"])
    rows = asyncio.run(run_replay(Settings(provider="stub", user_name="Safea"), con,
                                  contact="omar@example.org"))
    assert len(rows) == 1
    r = rows[0]
    assert not r.error and r.language == "ar" and r.status
    assert r.numbers_ref == 2 and 0 <= r.numbers_hit <= 2 and r.chrf >= 0
    assert r.real_reply.startswith("أهلاً عمر") and r.envoy_reply
    assert con.execute("SELECT count(*) AS n FROM history").fetchone()["n"] == 0  # not kept
    s = summarize(rows)
    assert s["n"] == 1 and s["errors"] == 0 and s["numbers_ref"] == 2
    text = render_replay(rows)
    assert "1 exchanges, 0 errors" in text and "omar@example.org" in text
    md = render([{"replay": replay_to_dicts(rows)}])
    assert "### Replay of your own inbox" in md and "| stub | 1 | 0 |" in md


def test_fullrun_quick_writes_every_file_and_one_report(tmp_path, monkeypatch):
    from envoy.cli import _fullrun

    monkeypatch.setenv("ENVOY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ENVOY_PROVIDER", "stub")
    monkeypatch.setenv("ENVOY_USER_EMAIL", "safea@example.com")
    con = db.connect(Settings.load().db_path)
    import_paths(con, [FIX / "sample.mbox"], my_addresses=["safea@example.com"])
    con.close()
    out = tmp_path / "results"
    _fullrun(Namespace(out=str(out), quick=True, models=None, critic_model=None, n=30))
    names = sorted(p.name for p in out.iterdir())
    assert names == ["heldout.json", "injection.json", "memory.json", "replay.json", "report.md"]
    heldout = json.loads((out / "heldout.json").read_text(encoding="utf-8"))
    assert len(heldout["runs"]) == 24 and heldout["perturbations"]  # 2 per locale, 12 locales
    injection = json.loads((out / "injection.json").read_text(encoding="utf-8"))
    assert len(injection["runs"]) == 21  # 3 attacks x 7 languages
    md = (out / "report.md").read_text(encoding="utf-8")
    for heading in ("### Checks", "### Perturbations", "### Memory on the fixture mailbox",
                    "### Replay of your own inbox"):
        assert heading in md, heading
