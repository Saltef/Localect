"""Facts extracted from mail, and what the Arbiter does when they disagree."""

import asyncio
from pathlib import Path

from envoy import db
from envoy.agents.arbiter import blocking, conflict_flags
from envoy.agents.extractor import normalize_extraction
from envoy.memory import import_paths
from envoy.memory.facts import extract_pending, topic_key, value_key
from envoy.models.stub import StubModel
from envoy.schemas import Claim, Draft, FlagKind, Segment
from envoy.tools import fact_snippets

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mail"


def test_topic_and_value_keys_fold_languages_and_digit_scripts():
    assert topic_key("return window") == topic_key("Return Window")
    # Real models write English topics; the alias table still folds the words
    # it knows when a topic comes in another language.
    assert "return" in topic_key("prazo de devolução").split()
    assert topic_key("devolução") == topic_key("return")
    assert topic_key("") == "" and topic_key("zzqx") == "zzqx"
    assert value_key("٣٠ أيام") == value_key("30 أيام") and value_key(" 30  days") == "30 days"


def test_normalize_extraction_drops_empty_statements_and_defaults():
    raw = {"facts": [{"topic": " Return Window ", "statement": "30 days.", "value": None},
                     {"topic": "x", "statement": ""}, "junk", {"statement": "no topic"}]}
    assert normalize_extraction(raw) == {"facts": [
        {"topic": "return window", "statement": "30 days.", "value": ""},
        {"topic": "untitled", "statement": "no topic", "value": ""}]}


def test_stub_extracts_dated_facts_from_the_fixture_mailbox():
    con = db.connect()
    import_paths(con, [FIX], my_addresses=["safea@example.com"])
    report = asyncio.run(extract_pending(con, StubModel()))
    assert report.messages == 6 and report.failed == 0 and report.facts >= 3
    assert db.messages_unextracted(con) == []
    facts = db.facts_search(con, "return window")
    assert {f["value"] for f in facts} == {"14", "30"}
    assert facts[0]["topic"] == "days return shipping"  # alias concepts, so both messages agree
    newest = facts[0]
    assert newest["value"] == "30" and newest["said_by"] == "you" \
        and newest["party"] == "layla@shop.example" and newest["said_on"].startswith("2025-09-10")
    # the same topic in two messages gets the same key, so they can conflict
    assert len({f["topic_key"] for f in facts}) == 1
    (group,) = db.facts_conflicts(con, party="layla@shop.example")
    assert [f["value"] for f in group] == ["30", "14"]
    # Arabic statement with Eastern digits becomes a fact too
    ar = [f for f in db.fact_list(con) if f["language"] == "ar"]
    assert ar and ar[0]["value"] in ("3", "5")
    # rejecting one removes the conflict; deleting the message removes its facts
    db.fact_update(con, facts[1]["id"], status="rejected")
    assert db.facts_conflicts(con) == []
    assert db.facts_search(con, "return window")[0]["id"] == newest["id"]
    db.message_delete(con, newest["message_id"])
    assert all(f["id"] != newest["id"] for f in db.fact_list(con))
    assert asyncio.run(extract_pending(con, StubModel())).messages == 0


def _fact(fid, value, said_on, topic="return window"):
    return fact_snippets([{"id": fid, "topic": topic, "topic_key": topic_key(topic),
                           "statement": f"{value} days", "value": value, "said_on": said_on,
                           "said_by": "you", "status": "auto"}])[0]


def test_arbiter_warns_when_the_newest_fact_is_used_and_blocks_a_stale_one():
    new, old = _fact("f1", "30", "2025-09-10"), _fact("f2", "14", "2025-09-01")
    assert new.id == "fc:f1" and new.meta["said"] == "you said on 2025-09-10"
    uses_new = Draft(language="en", segments=[
        Segment(id="s1", text="Hi,"),
        Segment(id="s2", text="30 days.", claims=[Claim(text="30 days", source_ids=["fc:f1"])])])
    (flag,) = conflict_flags(uses_new, [new, old])
    assert flag.kind == FlagKind.conflicting_sources and flag.severity == "warn"
    assert flag.segment_id == "s2" and "the newest was used" in flag.reason
    uses_old = Draft(language="en", segments=[
        Segment(id="s2", text="14 days.", claims=[Claim(text="14 days", source_ids=["fc:f2"])])])
    (flag,) = conflict_flags(uses_old, [new, old])
    assert flag.kind == FlagKind.stale_source and flag.severity == "block" and flag.span == "14"
    assert "was later changed" in flag.reason and blocking([flag]) == []  # a person decides
    # same value twice, or no citation: nothing to say
    assert conflict_flags(uses_new, [new, _fact("f3", "٣٠", "2025-08-01")]) == []
    assert conflict_flags(Draft(language="en", segments=[Segment(id="s1", text="x")]),
                          [new, old]) == []
    # different topics never conflict
    assert conflict_flags(uses_new, [new, _fact("f4", "12", "2025-09-15", "warranty length")]) \
        == []


def test_voice_examples_prefer_the_contact_and_the_language():
    con = db.connect()
    import_paths(con, [FIX], my_addresses=["safea@example.com"])
    v = db.voice_examples(con, "en", "jo@partner.example")
    assert v[0]["text"].startswith("Hi Jo") and len(v) == 3
    assert db.voice_examples(con, "ar")[0]["text"].startswith("أهلاً عمر")
    assert db.voice_examples(con, "ja") == []
    long = db.message_add(con, text="word " * 300, is_mine=True, date="2030-01-01T00:00:00Z",
                          language="en")
    assert long and db.voice_examples(con, "en", limit=1)[0]["text"].endswith(" …")


def test_facts_must_be_verifiably_in_the_message():
    from envoy.memory.facts import verify_provenance

    text = "Hi Layla,\n\nOur return window is 14 days from delivery. Items must be unused.\n\nBest"
    assert verify_provenance("Our return window is 14 days from delivery.", text)
    assert verify_provenance("our return window is 14 days from delivery", text)  # case, punct
    assert verify_provenance("Return window is 14 days from delivery", text)  # trimmed clause
    assert verify_provenance("مدة الإرجاع ٣٠ يوم", "أهلاً، مدة الإرجاع 30 يوم من الاستلام.")
    assert not verify_provenance("Our return window is 30 days from delivery.", text)  # number
    assert not verify_provenance("Free shipping on every order.", text)  # invented
    assert not verify_provenance("", text)


async def test_extraction_drops_invented_facts_and_counts_them():
    from envoy.memory.facts import ExtractReport, extract_message
    from envoy.models.base import FakeModel

    con = db.connect()
    mid = db.message_add(con, text="The warranty is 12 months.", date="2025-01-01T00:00:00Z",
                         from_addr="safea@example.com", is_mine=True, language="en")
    model = FakeModel(['{"facts": [{"topic": "warranty length", "statement": "The warranty is '
                       '12 months.", "value": "12 months"}, {"topic": "warranty length", '
                       '"statement": "The warranty is 24 months.", "value": "24 months"}]}'])
    report = ExtractReport()
    assert await extract_message(con, model, db.message_get(con, mid), report) == 1
    assert report.unverified == 1
    assert [f["value"] for f in db.fact_list(con)] == ["12 months"]
