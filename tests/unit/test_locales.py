from envoy import db
from envoy.locales import load_starter_profiles, seed_locales


def test_twelve_profiles_load_with_arabic_rtl():
    ps = load_starter_profiles()
    assert len(ps) == 12
    by = {p.locale: p for p in ps}
    assert by["ar-EG"].rtl and by["ar-EG"].formats.numerals == "eastern-arabic"
    assert by["de-DE"].formats.date == "DD.MM.YYYY"
    assert "{name}" in by["ja-JP"].greeting


def test_seed_is_idempotent(con):
    assert seed_locales(con) == 0  # fixture already seeded
    assert len(db.locale_list(con)) == 12
