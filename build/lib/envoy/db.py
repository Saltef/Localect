"""SQLite storage: settings, glossary, locales, contacts, knowledge, history.

Plain sqlite3, one file, no ORM. Every function takes a connection so tests can
use an in-memory database.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from .schemas import LocaleProfile
from .text import score as _score
from .text import tokens as _tokens

SCHEMA = """
CREATE TABLE IF NOT EXISTS glossary (
  id TEXT PRIMARY KEY, term TEXT NOT NULL, language TEXT NOT NULL DEFAULT '*',
  rendering TEXT NOT NULL DEFAULT '', do_not_translate INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS locales (
  locale TEXT PRIMARY KEY, profile TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, locale TEXT NOT NULL, notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS knowledge (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, message TEXT NOT NULL,
  locale TEXT NOT NULL, status TEXT NOT NULL, final_text TEXT NOT NULL,
  result TEXT NOT NULL, contact_id TEXT NOT NULL DEFAULT ''
);
"""


def connect(path: Path | str = ":memory:") -> sqlite3.Connection:
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _uid() -> str:
    return uuid4().hex[:10]


# --- glossary ----------------------------------------------------------------


def glossary_add(con, term: str, rendering: str = "", language: str = "*",
                 do_not_translate: bool = False, notes: str = "") -> str:
    gid = _uid()
    con.execute(
        "INSERT INTO glossary VALUES (?,?,?,?,?,?)",
        (gid, term, language, rendering, int(do_not_translate), notes),
    )
    con.commit()
    return gid


def glossary_list(con) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute("SELECT * FROM glossary ORDER BY term")]


def glossary_delete(con, gid: str) -> None:
    con.execute("DELETE FROM glossary WHERE id=?", (gid,))
    con.commit()


def glossary_lookup(con, text: str, language: str) -> list[dict[str, Any]]:
    """Every glossary entry whose term appears in ``text`` and applies to ``language``."""
    low = text.lower()
    hits = []
    for r in con.execute("SELECT * FROM glossary"):
        if r["term"].lower() in low and r["language"] in ("*", language):
            hits.append(dict(r))
    return hits


# --- locales -----------------------------------------------------------------


def locale_upsert(con, profile: LocaleProfile) -> None:
    con.execute(
        "INSERT OR REPLACE INTO locales VALUES (?,?)",
        (profile.locale, profile.model_dump_json()),
    )
    con.commit()


def locale_get(con, locale: str) -> LocaleProfile | None:
    r = con.execute("SELECT profile FROM locales WHERE locale=?", (locale,)).fetchone()
    return LocaleProfile.model_validate_json(r["profile"]) if r else None


def locale_list(con) -> list[LocaleProfile]:
    return [
        LocaleProfile.model_validate_json(r["profile"])
        for r in con.execute("SELECT profile FROM locales ORDER BY locale")
    ]


def locale_for_language(con, language: str) -> LocaleProfile | None:
    for p in locale_list(con):
        if p.language == language:
            return p
    return None


# --- contacts ----------------------------------------------------------------


def contact_add(con, name: str, locale: str, notes: str = "") -> str:
    cid = _uid()
    con.execute("INSERT INTO contacts VALUES (?,?,?,?)", (cid, name, locale, notes))
    con.commit()
    return cid


def contact_list(con) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute("SELECT * FROM contacts ORDER BY name")]


def contact_get(con, cid: str) -> dict[str, Any] | None:
    r = con.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return dict(r) if r else None


def contact_delete(con, cid: str) -> None:
    con.execute("DELETE FROM contacts WHERE id=?", (cid,))
    con.commit()


# --- knowledge ---------------------------------------------------------------


def knowledge_add(con, title: str, text: str) -> str:
    kid = _uid()
    con.execute("INSERT INTO knowledge VALUES (?,?,?)", (kid, title, text))
    con.commit()
    return kid


def knowledge_list(con) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute("SELECT id, title, length(text) AS size FROM knowledge")]


def knowledge_delete(con, kid: str) -> None:
    con.execute("DELETE FROM knowledge WHERE id=?", (kid,))
    con.commit()


def knowledge_search(con, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Token-overlap search over paragraphs, returning snippets with offsets."""
    terms = _tokens(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in con.execute("SELECT * FROM knowledge"):
        text = r["text"]
        offset = 0
        for para in text.split("\n\n"):
            score = _score(_tokens(para), terms)
            if score:
                scored.append((score, {
                    "id": f"{r['id']}:{offset}",
                    "title": r["title"],
                    "text": para.strip(),
                    "start": offset,
                    "end": offset + len(para),
                }))
            offset += len(para) + 2
    scored.sort(key=lambda s: -s[0])
    return [s for _, s in scored[:limit]]


# --- history -----------------------------------------------------------------


def history_add(con, result_json: str, rid: str, created_at: str, message: str,
                locale: str, status: str, final_text: str, contact_id: str = "") -> None:
    con.execute(
        "INSERT OR REPLACE INTO history VALUES (?,?,?,?,?,?,?,?)",
        (rid, created_at, message, locale, status, final_text, result_json, contact_id),
    )
    con.commit()


def history_thread(con, contact_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Recent exchanges with one contact, oldest first."""
    rows = con.execute(
        "SELECT id, created_at, message, final_text FROM history WHERE contact_id=? "
        "ORDER BY created_at DESC LIMIT ?", (contact_id, limit)
    )
    return [dict(r) for r in rows][::-1]


def history_list(con, limit: int = 50) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT id, created_at, message, locale, status, final_text FROM history "
        "ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    return [dict(r) for r in rows]


def history_get(con, rid: str) -> dict[str, Any] | None:
    r = con.execute("SELECT result FROM history WHERE id=?", (rid,)).fetchone()
    return json.loads(r["result"]) if r else None


def history_search(con, query: str, language: str | None = None, limit: int = 3
                   ) -> list[dict[str, Any]]:
    """Past final replies with overlapping vocabulary, for voice and precedent."""
    terms = _tokens(query)
    scored = []
    for r in con.execute("SELECT id, message, locale, final_text FROM history"):
        if language and not r["locale"].startswith(language):
            continue
        score = _score(_tokens(r["message"]), terms)
        if score:
            scored.append((score, dict(r)))
    scored.sort(key=lambda s: -s[0])
    return [s for _, s in scored[:limit]]
