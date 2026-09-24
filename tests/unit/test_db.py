from envoy import db


def test_glossary_lookup_filters_by_language(con):
    db.glossary_add(con, "SkyPack", do_not_translate=True)
    db.glossary_add(con, "store credit", "رصيد", "ar")
    db.glossary_add(con, "store credit", "crédito", "pt")
    hits = db.glossary_lookup(con, "about SkyPack and store credit", "ar")
    assert {h["term"] for h in hits} == {"SkyPack", "store credit"}
    assert [h["rendering"] for h in hits if h["term"] == "store credit"] == ["رصيد"]


def test_knowledge_search_is_cross_lingual_and_anchored(con):
    kid = db.knowledge_add(con, "Ship",
                           "Orders ship within 2 business days.\n\nReturns take 30 days.")
    hits = db.knowledge_search(con, "cuándo llega mi pedido")
    assert hits and hits[0]["id"] == f"{kid}:0"
    assert hits[0]["start"] == 0 and hits[0]["text"].startswith("Orders ship")


def test_history_thread_is_per_contact(con):
    db.history_add(con, "{}", "r1", "2026-01-01T00:00:00", "hi", "en-US", "ready", "hello", "c1")
    db.history_add(con, "{}", "r2", "2026-01-02T00:00:00", "hey", "en-US", "ready", "yo", "c2")
    assert [r["id"] for r in db.history_thread(con, "c1")] == ["r1"]


def test_contacts_carry_a_gender_and_old_databases_are_migrated():
    import sqlite3

    from envoy import db

    con = db.connect()
    cid = db.contact_add(con, "Mona", "ar-EG", gender="female")
    assert db.contact_get(con, cid)["gender"] == "female"
    assert db.contact_get(con, db.contact_add(con, "X", "en-US", gender="banana"))["gender"] \
        == "unknown"
    # A database created before the column existed.
    old = sqlite3.connect(":memory:")
    old.row_factory = sqlite3.Row
    old.executescript("CREATE TABLE contacts (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                      "locale TEXT NOT NULL, notes TEXT NOT NULL DEFAULT ''); "
                      "CREATE TABLE locales (locale TEXT PRIMARY KEY, profile TEXT NOT NULL); "
                      "INSERT INTO contacts VALUES ('c1', 'Layla', 'ar-LB', '')")
    db._migrate(old)
    assert dict(old.execute("SELECT * FROM contacts").fetchone())["gender"] == "unknown"
