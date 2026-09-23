"""Each model-driven agent with a canned-reply model: prompt assembly and parsing."""

import json

from envoy.agents import critic, drafter, reader, rewriter
from envoy.models.base import FakeModel
from envoy.schemas import (
    Draft,
    Flag,
    FlagKind,
    LocaleProfile,
    Reading,
    Rewrite,
    RewrittenSegment,
    Segment,
    SourceSnippet,
)

LOCALE = LocaleProfile(locale="ar-EG", language="ar", language_name="Arabic",
                       region_name="Egypt", variety="Egyptian Arabic", greeting="أهلاً {name}،",
                       signoff="تحياتي،", notes="avoid: stiff phrasing", rtl=True)
READING = Reading(language="ar", gloss="When does order #1 ship?", intent="shipping",
                  asks=["When does order #1 ship?"], must_preserve=["#1"])
SRC = [SourceSnippet(id="kb:1", kind="knowledge", text="Orders ship in 2 days."),
       SourceSnippet(id="gl:1", kind="glossary", text="SkyPack: do not translate",
                     meta={"term": "SkyPack", "do_not_translate": 1, "rendering": ""})]


async def test_reader_prompt_and_parse():
    m = FakeModel([json.dumps({"language": "ar", "gloss": "g", "intent": "i", "asks": ["a?"]})])
    r = await reader.read(m, "مرحبا", "English")
    assert r.asks == ["a?"]
    prompt = m.calls[0]["messages"][1]["content"]
    assert "مرحبا" in prompt and "English" in prompt and '"properties"' in prompt


async def test_drafter_sees_sources_glossary_and_names():
    m = FakeModel([json.dumps({"language": "ar", "segments": [
        {"id": "s1", "text": "hi", "claims": [{"text": "2 days", "source_ids": ["kb:1"]}]}]})])
    d = await drafter.draft(m, READING, LOCALE, SRC, user_language_name="English",
                            contact_name="Layla", user_name="Safea")
    assert d.segments[0].claims[0].source_ids == ["kb:1"]
    p = m.calls[0]["messages"][1]["content"]
    assert "[kb:1]" in p and "SkyPack: do not translate" in p and "Layla" in p and "Safea" in p


async def test_rewriter_includes_flags_on_revision():
    d = Draft(language="ar", segments=[Segment(id="s1", text="x")])
    m = FakeModel([json.dumps({"segments": [{"id": "s1", "text": "y"}], "changes": []})])
    fl = [Flag(segment_id="s1", kind=FlagKind.drifted, span="#1", reason="lost #1",
               severity="block")]
    rw = await rewriter.rewrite(m, d, LOCALE, SRC, ["#1"], fl)
    assert rw.text() == "y"
    p = m.calls[0]["messages"][1]["content"]
    assert "reviewer flagged" in p and "lost #1" in p and "Egyptian Arabic" in p
    assert m.calls[0]["context"]["revise"] is True


async def test_critic_gets_draft_final_and_sources():
    d = Draft(language="ar", segments=[Segment(id="s1", text="draft text")])
    rw = Rewrite(segments=[RewrittenSegment(id="s1", text="final text")])
    m = FakeModel([json.dumps({"back_segments": [{"id": "s1", "text": "bt"}], "flags": [
        {"segment_id": "s1", "kind": "tone_off", "reason": "casual", "severity": "warn"}]})])
    cq = await critic.critique(m, d, rw, LOCALE, SRC, ["#1"], "English")
    assert cq.flags[0].kind == FlagKind.tone_off and cq.back_translation() == "bt"
    p = m.calls[0]["messages"][1]["content"]
    assert "draft text" in p and "final text" in p and "[kb:1]" in p
