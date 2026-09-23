from envoy.conventions import enforce, quiet_critic, rendered_greeting, rendered_signoff
from envoy.schemas import (
    BackSegment,
    Claim,
    Critique,
    Flag,
    FlagKind,
    LocaleProfile,
    RewrittenSegment,
    Segment,
    Suggestion,
)

EG = LocaleProfile(locale="ar-EG", language="ar", language_name="Arabic", region_name="Egypt",
                   variety="Egyptian Arabic", greeting="أهلاً بيك {name}،", signoff="تحياتي،")
GB = LocaleProfile(locale="en-GB", language="en", language_name="English",
                   region_name="United Kingdom", variety="British English",
                   greeting="Hi {name},", signoff="Kind regards,")


def test_rendered_conventions():
    assert rendered_greeting(EG, "") == "أهلاً بيك،"
    assert rendered_greeting(GB, "") == "Hi there,"
    assert rendered_greeting(GB, "Layla") == "Hi Layla,"
    assert rendered_signoff(GB, "Safea") == "Kind regards,\nSafea"


def test_enforce_replaces_improvised_greeting_and_signoff():
    segs = [Segment(id="g1", text="Hi Safea,"),
            Segment(id="s1", text="Your order ships in 2 days.",
                    claims=[Claim(text="2 days", source_ids=["kb:1"])]),
            Segment(id="c1", text="Best regards, Safea")]
    changed = enforce(segs, GB, "", "Safea")
    assert changed == ["g1", "c1"]
    assert segs[0].text == "Hi there," and segs[-1].text == "Kind regards,\nSafea"
    assert segs[1].text.startswith("Your order")  # body untouched


def test_enforce_leaves_long_or_claim_bearing_segments_alone():
    segs = [Segment(id="s1", text="Hi Safea, thanks for writing about order #1, it ships soon "
                                  "and tracking follows by email.")]
    assert enforce(segs, GB, "", "Safea") == []


def test_enforce_works_on_rewritten_segments():
    segs = [RewrittenSegment(id="g1", text="أهلاً عميلنا العزيز،"),
            RewrittenSegment(id="s1", text="المبلغ هيرجعلك خلال ٥ أيام."),
            RewrittenSegment(id="c1", text="مع خالص التقدير،")]
    enforce(segs, EG, "", "Safea", has_claims=lambda s: False)
    assert segs[0].text == "أهلاً بيك،" and segs[-1].text == "تحياتي،\nSafea"


def test_quiet_critic_drops_convention_flags_and_noop_suggestions():
    cq = Critique(
        back_segments=[BackSegment(id="g1", text="Hello,")],
        flags=[Flag(segment_id="g1", kind=FlagKind.tone_off, reason="too casual"),
               Flag(segment_id="s1", kind=FlagKind.drifted, span="#1", reason="lost",
                    severity="block")],
        suggestions=[Suggestion(segment_id="c1", suggestion="تحياتي،"),
                     Suggestion(segment_id="s1", suggestion="say it simpler")],
    )
    final = {"g1": "أهلاً بيك،", "s1": "body", "c1": "تحياتي،\nSafea"}
    out = quiet_critic(cq, final, EG, "", "Safea")
    assert [f.kind for f in out.flags] == [FlagKind.drifted]
    assert [s.segment_id for s in out.suggestions] == ["s1"]
