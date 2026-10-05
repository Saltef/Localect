from localect.conventions import enforce, quiet_critic, rendered_greeting, rendered_signoff
from localect.schemas import (
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


def test_enforce_collapses_split_closing_into_one_signoff():
    segs = [RewrittenSegment(id="g1", text="أهلاً بيك،"),
            RewrittenSegment(id="s1",
                             text="المبلغ هيرجعلك خلال ٥ أيام عمل من وقت ما نستلم المرتجع."),
            RewrittenSegment(id="c1", text="تحياتي،"),
            RewrittenSegment(id="c2", text="Safea")]
    enforce(segs, EG, "", "Safea", has_claims=lambda s: False)
    assert [s.id for s in segs] == ["g1", "s1", "c1"]
    assert segs[-1].text == "تحياتي،\nSafea"


def test_enforce_keeps_a_real_closing_sentence():
    segs = [RewrittenSegment(id="g1", text="Hi there,"),
            RewrittenSegment(id="s1", text="Your order ships within 2 business days."),
            RewrittenSegment(id="s2", text="If there is anything else at all, I am happy to help."),
            RewrittenSegment(id="c1", text="Kind regards, Safea")]
    enforce(segs, GB, "", "Safea", has_claims=lambda s: False)
    assert [s.id for s in segs] == ["g1", "s1", "s2", "c1"]
    assert segs[2].text.startswith("If there is") and segs[-1].text == "Kind regards,\nSafea"


def test_gendered_forms_are_used_only_when_the_gender_is_known():
    from localect.conventions import greeting_form, signoff_form

    eg = LocaleProfile(locale="ar-EG", language="ar", language_name="Arabic",
                       region_name="Egypt", variety="Egyptian Arabic",
                       greeting="أهلاً وسهلاً {name}،", signoff="تحياتي،",
                       greetings={"female": "أهلاً بيكي {name}،", "male": "أهلاً بيك {name}،"})
    assert rendered_greeting(eg, "منى", "female") == "أهلاً بيكي منى،"
    assert rendered_greeting(eg, "عمر", "male") == "أهلاً بيك عمر،"
    assert rendered_greeting(eg, "", "unknown") == "أهلاً وسهلاً،"
    assert greeting_form(eg, "other") == eg.greeting and signoff_form(eg, "female") == "تحياتي،"
    assert rendered_greeting(GB, "Sam", "female") == "Hi Sam,"  # no variants: neutral form

    segs = [RewrittenSegment(id="g1", text="أهلاً عميلنا العزيز،"),
            RewrittenSegment(id="s1", text="المبلغ هيرجعلك خلال ٥ أيام."),
            RewrittenSegment(id="c1", text="مع خالص التقدير،")]
    enforce(segs, eg, "منى", "Safea", gender="female", has_claims=lambda s: False)
    assert segs[0].text == "أهلاً بيكي منى،"


def test_every_starter_arabic_locale_greets_both_genders_correctly():
    from localect.locales import load_starter_profiles

    for p in load_starter_profiles():
        if p.language != "ar":
            continue
        f, m, u = (rendered_greeting(p, "", g) for g in ("female", "male", "unknown"))
        assert f and m and u, p.locale
        if p.greetings:
            assert f != m, f"{p.locale}: female and male forms must differ"
            assert u not in (f, m), f"{p.locale}: the unknown form must be neutral"


JA = LocaleProfile(locale="ja-JP", language="ja", language_name="Japanese", region_name="Japan",
                   variety="Standard Japanese", greeting="{name}様\n\nお世話になっております。",
                   signoff="何卒よろしくお願いいたします。")


def test_enforce_measures_japanese_in_characters_not_whitespace_tokens():
    # Japanese has no word spaces, so every segment used to count as "short"
    # and the sign-off walk swallowed the body of the reply.
    segs = [RewrittenSegment(id="g1", text="お客様\n\nいつもお世話になっております。"),
            RewrittenSegment(id="s1", text="ご注文の商品は2日以内に発送いたします。"),
            RewrittenSegment(id="s2", text="追跡番号は発送後にメールでお知らせいたします。"),
            RewrittenSegment(id="c1", text="今後ともよろしくお願い申し上げます。"),
            RewrittenSegment(id="c2", text="Safea")]
    changed = enforce(segs, JA, "", "Safea", has_claims=lambda s: False)
    assert changed == ["g1", "c1"]
    assert [s.id for s in segs] == ["g1", "s1", "s2", "c1"]
    assert segs[0].text == "お客様\n\nお世話になっております。"
    assert segs[1].text.startswith("ご注文") and segs[2].text.startswith("追跡番号")
    assert segs[-1].text == "何卒よろしくお願いいたします。\nSafea"


def test_enforce_never_replaces_a_segment_that_carries_a_number():
    segs = [Segment(id="s1", text="Order #3030 ships in 2 days."),
            Segment(id="c1", text="Refund in ٥ days, regards")]
    assert enforce(segs, GB, "", "Safea") == []
    assert segs[1].text == "Refund in ٥ days, regards"
