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


def test_seed_refreshes_starter_profiles_but_not_user_edits(con):
    from envoy.schemas import LocaleProfile

    eg = db.locale_get(con, "ar-EG")
    stale = eg.model_copy(update={"greeting": "old {name}،"})
    db.locale_upsert(con, stale, origin="starter")
    assert seed_locales(con) == 1  # refreshed from the shipped YAML
    assert db.locale_get(con, "ar-EG").greeting == eg.greeting
    mine = eg.model_copy(update={"greeting": "يا {name}،"})
    db.locale_upsert(con, mine)  # user edit
    assert seed_locales(con) == 0
    assert db.locale_get(con, "ar-EG").greeting == "يا {name}،"
    assert isinstance(db.locale_get(con, "de-DE"), LocaleProfile)


def test_migration_adds_origin_column_to_old_database(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE locales (locale TEXT PRIMARY KEY, profile TEXT NOT NULL)")
    raw.commit()
    raw.close()
    con = db.connect(path)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(locales)")}
    assert "origin" in cols
    assert seed_locales(con) == 12
