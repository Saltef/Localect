from envoy.agents import arbiter
from envoy.schemas import (
    BackSegment,
    Claim,
    Critique,
    Draft,
    Flag,
    FlagKind,
    Rewrite,
    RewrittenSegment,
    Segment,
    SourceSnippet,
    Status,
)


def _draft(text="Order #4521 ships in 2 days.", claims=None):
    return Draft(language="en", segments=[Segment(id="s1", text=text, claims=claims or [])])


def _rw(text):
    return Rewrite(segments=[RewrittenSegment(id="s1", text=text)])


def _cq(text, flags=()):
    return Critique(back_segments=[BackSegment(id="s1", text=text)], flags=list(flags))


def test_ready_when_faithful():
    flags, status, ledger = arbiter.check(_draft(), _rw("Order #4521 ships in ٢ days."),
                                          _cq("x"), ["#4521", "2"], [])
    assert status == Status.ready and flags == []
    assert ledger[0].final_text.endswith("٢ days.")


def test_drifted_when_preserved_item_missing():
    flags, status, _ = arbiter.check(_draft(), _rw("Your order ships soon."), _cq("x"),
                                     ["#4521"], [])
    assert status == Status.escalate
    assert flags[0].kind == FlagKind.drifted and flags[0].span == "#4521"


def test_off_glossary_for_do_not_translate_term():
    src = SourceSnippet(id="gl:1", kind="glossary", text="SkyPack: do not translate",
                        meta={"term": "SkyPack", "do_not_translate": 1, "rendering": ""})
    flags, status, _ = arbiter.check(_draft("SkyPack ships today."), _rw("Sky Pack ships today."),
                                     _cq("x"), [], [src])
    assert status == Status.escalate and flags[0].kind == FlagKind.off_glossary


def test_unsupported_claim_blocks():
    d = _draft(claims=[Claim(text="full refund guaranteed", source_ids=[])])
    flags, status, _ = arbiter.check(d, _rw(d.segments[0].text), _cq("x"), [], [])
    assert status == Status.escalate and flags[0].kind == FlagKind.unsupported_claim
    assert arbiter.blocking(flags) == []  # not something a rewrite can fix


def test_dropped_segment_is_missing_item():
    flags, status, _ = arbiter.check(_draft(), Rewrite(segments=[]),
                                     Critique(back_segments=[]), [], [])
    assert flags[0].kind == FlagKind.missing_item and status == Status.escalate


def test_warn_only_gives_check_and_dedupes_with_critic():
    warn = Flag(segment_id="s1", kind=FlagKind.tone_off, reason="too casual", severity="warn")
    dup = Flag(segment_id="s1", kind=FlagKind.drifted, span="#4521", reason="x", severity="block")
    flags, status, _ = arbiter.check(_draft(), _rw("Your order ships soon."),
                                     _cq("x", [warn, dup]), ["#4521"], [])
    assert status == Status.escalate
    blocking = [f for f in flags if f.kind == FlagKind.drifted and f.severity == "block"]
    assert len(blocking) == 1  # the Critic's duplicate of the Arbiter's own finding is dropped
    flags, status, _ = arbiter.check(_draft(), _rw(_draft().segments[0].text),
                                     _cq("x", [warn]), [], [])
    assert status == Status.check


def test_numbers_dropped_or_invented_by_the_rewrite_are_warned_about():
    from envoy.agents.arbiter import number_flags

    flags = number_flags("s2", "Returns within 30 days; refund in 5 business days. Order #4521.",
                         "Returns within 45 days; refund in ٥ business days. Order #4521.",
                         ["#4521"])
    assert [(f.kind.value, f.span, f.severity) for f in flags] == [
        ("drifted", "30", "warn"), ("unsupported_claim", "45", "warn")]
    # Reformatting a date is not a drift.
    assert number_flags("s1", "Delivered on 2024-05-01.", "Delivered on 01/05/2024.", []) == []
