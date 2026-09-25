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

from .conventions import GENDERS
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
  locale TEXT PRIMARY KEY, profile TEXT NOT NULL, origin TEXT NOT NULL DEFAULT 'starter'
);
CREATE TABLE IF NOT EXISTS contacts (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, locale TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
  gender TEXT NOT NULL DEFAULT 'unknown', email TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS knowledge (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, external_id TEXT NOT NULL DEFAULT '', thread_id TEXT NOT NULL DEFAULT '',
  date TEXT NOT NULL DEFAULT '', from_addr TEXT NOT NULL DEFAULT '',
  from_name TEXT NOT NULL DEFAULT '', to_addrs TEXT NOT NULL DEFAULT '',
  subject TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, is_mine INTEGER NOT NULL DEFAULT 0,
  language TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT 'import',
  source TEXT NOT NULL DEFAULT '', extracted_at TEXT NOT NULL DEFAULT '',
  excluded INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS messages_external ON messages(external_id)
  WHERE external_id <> '';
CREATE TABLE IF NOT EXISTS exclusions (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '',
  UNIQUE (kind, value)
);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, topic TEXT NOT NULL, topic_key TEXT NOT NULL, statement TEXT NOT NULL,
  value TEXT NOT NULL DEFAULT '', said_on TEXT NOT NULL DEFAULT '',
  said_by TEXT NOT NULL DEFAULT 'them', party TEXT NOT NULL DEFAULT '',
  message_id TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'auto', created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS embeddings (
  kind TEXT NOT NULL, ref TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL,
  vector BLOB NOT NULL, PRIMARY KEY (kind, ref, model)
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
    _migrate(con)
    return con


def _migrate(con: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(locales)")}
    if "origin" not in cols:
        con.execute("ALTER TABLE locales ADD COLUMN origin TEXT NOT NULL DEFAULT 'starter'")
        con.commit()
    cols = {r["name"] for r in con.execute("PRAGMA table_info(messages)")}
    if cols and "extracted_at" not in cols:
        con.execute("ALTER TABLE messages ADD COLUMN extracted_at TEXT NOT NULL DEFAULT ''")
    if cols and "excluded" not in cols:
        con.execute("ALTER TABLE messages ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0")
    cols = {r["name"] for r in con.execute("PRAGMA table_info(contacts)")}
    if "email" not in cols:
        con.execute("ALTER TABLE contacts ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    if "gender" not in cols:
        con.execute("ALTER TABLE contacts ADD COLUMN gender TEXT NOT NULL DEFAULT 'unknown'")
        con.commit()


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


def locale_upsert(con, profile: LocaleProfile, origin: str = "user") -> None:
    con.execute(
        "INSERT OR REPLACE INTO locales (locale, profile, origin) VALUES (?,?,?)",
        (profile.locale, profile.model_dump_json(), origin),
    )
    con.commit()


def locale_origin(con, locale: str) -> str | None:
    r = con.execute("SELECT origin FROM locales WHERE locale=?", (locale,)).fetchone()
    return r["origin"] if r else None


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


def contact_add(con, name: str, locale: str, notes: str = "", gender: str = "unknown",
                email: str = "") -> str:
    cid = _uid()
    con.execute("INSERT INTO contacts (id, name, locale, notes, gender, email) VALUES "
                "(?,?,?,?,?,?)", (cid, name, locale, notes,
                                 gender if gender in GENDERS else "unknown",
                                 email.strip().lower()))
    con.commit()
    return cid


def contact_list(con) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute("SELECT * FROM contacts ORDER BY name")]


def contact_get(con, cid: str) -> dict[str, Any] | None:
    r = con.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return dict(r) if r else None


def contact_by_email(con, email: str) -> dict[str, Any] | None:
    if not email:
        return None
    r = con.execute("SELECT * FROM contacts WHERE email=?", (email.strip().lower(),)).fetchone()
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
    con.execute("DELETE FROM embeddings WHERE kind='knowledge' AND ref LIKE ?", (kid + ":%",))
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


# --- messages: the user's past mail, imported or captured ----------------------


def message_add(con, *, text: str, external_id: str = "", thread_id: str = "", date: str = "",
                from_addr: str = "", from_name: str = "", to_addrs: str = "", subject: str = "",
                is_mine: bool = False, language: str = "", origin: str = "import",
                source: str = "") -> str | None:
    """Store one message. Returns its id, or None when the same message (by
    Message-ID) is already stored, so an export can be imported twice."""
    mid = _uid()
    excluded = is_excluded(con, thread_id, from_addr, to_addrs)
    cur = con.execute(
        "INSERT OR IGNORE INTO messages (id, external_id, thread_id, date, from_addr, from_name, "
        "to_addrs, subject, text, is_mine, language, origin, source, excluded) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, external_id, thread_id, date, from_addr.lower(), from_name, to_addrs.lower(),
         subject, text, int(is_mine), language, origin, source, int(excluded)))
    return mid if cur.rowcount else None


def message_list(con, limit: int = 200, query: str = "") -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT id, external_id, thread_id, date, from_addr, from_name, to_addrs, subject, "
        "substr(text, 1, 240) AS preview, length(text) AS size, is_mine, language, origin, "
        "source, excluded FROM messages ORDER BY date DESC LIMIT ?",
        (limit * 4 if query else limit,))
    out = [dict(r) for r in rows]
    if query:
        q = query.lower()
        out = [m for m in out if q in (m["subject"] + " " + m["preview"] + " "
                                       + m["from_addr"] + " " + m["from_name"]).lower()]
    return out[:limit]


def message_get(con, mid: str) -> dict[str, Any] | None:
    r = con.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    return dict(r) if r else None


def message_delete(con, mid: str) -> None:
    con.execute("DELETE FROM messages WHERE id=?", (mid,))
    con.execute("DELETE FROM embeddings WHERE kind='mail' AND ref LIKE ?", (mid + ":%",))
    con.execute("DELETE FROM facts WHERE message_id=?", (mid,))
    con.commit()


def messages_unextracted(con, limit: int = 1000) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM messages WHERE extracted_at='' AND excluded=0 ORDER BY date LIMIT ?",
        (limit,))]


def message_mark_extracted(con, mid: str, when: str) -> None:
    con.execute("UPDATE messages SET extracted_at=? WHERE id=?", (when, mid))


def voice_examples(con, language: str | None, contact_email: str = "", limit: int = 3,
                   max_chars: int = 400) -> list[dict[str, Any]]:
    """The user's own recent messages in this language, to this contact when
    there are any: how they write, for the Rewriter to match."""
    contact_email = (contact_email or "").strip().lower()
    rows = [dict(r) for r in con.execute(
        "SELECT id, date, to_addrs, subject, text, language FROM messages WHERE is_mine=1 "
        "AND excluded=0 ORDER BY date DESC LIMIT 200")]
    if language:
        rows = [r for r in rows if not r["language"] or r["language"].startswith(language)]
    rows.sort(key=lambda r: (bool(contact_email) and contact_email in r["to_addrs"], r["date"]),
              reverse=True)
    out = []
    for r in rows[:limit]:
        text = r["text"] if len(r["text"]) <= max_chars else r["text"][:max_chars].rsplit(
            " ", 1)[0] + " …"
        out.append({"id": r["id"], "date": r["date"], "subject": r["subject"], "text": text})
    return out


# --- facts: dated statements extracted from messages --------------------------


def fact_add(con, *, topic: str, topic_key: str, statement: str, value: str = "",
             said_on: str = "", said_by: str = "them", party: str = "", message_id: str = "",
             language: str = "", status: str = "auto", created_at: str = "") -> str:
    fid = _uid()
    con.execute(
        "INSERT INTO facts (id, topic, topic_key, statement, value, said_on, said_by, party, "
        "message_id, language, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (fid, topic, topic_key, statement, value, said_on, said_by, party.lower(), message_id,
         language, status, created_at))
    return fid


def fact_get(con, fid: str) -> dict[str, Any] | None:
    r = con.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
    return dict(r) if r else None


def fact_list(con, query: str = "", party: str = "", status: str = "", limit: int = 200
              ) -> list[dict[str, Any]]:
    rows = [dict(r) for r in con.execute("SELECT * FROM facts ORDER BY said_on DESC")]
    q = query.lower()
    party = party.strip().lower()
    out = [r for r in rows
           if (not q or q in (r["topic"] + " " + r["statement"] + " " + r["value"]).lower())
           and (not party or r["party"] == party) and (not status or r["status"] == status)]
    return out[:limit]


def fact_update(con, fid: str, **fields) -> dict[str, Any] | None:
    allowed = {"topic", "topic_key", "statement", "value", "status"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if sets:
        con.execute("UPDATE facts SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE id=?",
                    (*sets.values(), fid))
        con.commit()
    return fact_get(con, fid)


def fact_delete(con, fid: str) -> None:
    con.execute("DELETE FROM facts WHERE id=?", (fid,))
    con.commit()


def fact_count(con) -> dict[str, int]:
    out = {"facts": 0, "auto": 0, "confirmed": 0, "rejected": 0}
    for r in con.execute("SELECT status, count(*) AS n FROM facts GROUP BY status"):
        out[r["status"]] = r["n"]
        out["facts"] += r["n"]
    return out


# Facts that may be used: not rejected, and not from an excluded message.
_LIVE_FACTS = ("SELECT * FROM facts WHERE status<>'rejected' AND message_id NOT IN "
               "(SELECT id FROM messages WHERE excluded=1)")


def facts_for_message(con, mid: str) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute("SELECT * FROM facts WHERE message_id=? ORDER BY said_on",
                                         (mid,))]


def facts_search(con, query: str, language: str | None = None, party: str = "",
                 limit: int = 6) -> list[dict[str, Any]]:
    """Facts whose topic or statement overlaps the query, rejected ones
    excluded, ranked by overlap, then the party being answered, then
    confirmed over automatic, then newest. Facts carry their topic key so the
    Arbiter can see when two of them disagree."""
    terms = _tokens(query)
    if not terms:
        return []
    party = (party or "").strip().lower()
    scored = []
    for r in con.execute(_LIVE_FACTS):
        score = _score(_tokens(r["topic"] + " " + r["statement"]), terms)
        if not score:
            continue
        scored.append(((score, int(bool(party) and r["party"] == party),
                        int(r["status"] == "confirmed"), r["said_on"]), dict(r)))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [s for _, s in scored[:limit]]


def facts_conflicts(con, party: str = "") -> list[list[dict[str, Any]]]:
    """Groups of facts on the same topic with different values."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in con.execute(_LIVE_FACTS + " ORDER BY said_on DESC"):
        if party and r["party"] and r["party"] != party.lower():
            continue
        if r["value"]:
            groups.setdefault(r["topic_key"], []).append(dict(r))
    return [g for g in groups.values() if len({f["value"] for f in g}) > 1]


def message_count(con) -> dict[str, int]:
    r = con.execute("SELECT count(*) AS n, coalesce(sum(is_mine), 0) AS mine, "
                    "coalesce(sum(excluded), 0) AS excluded FROM messages").fetchone()
    return {"messages": r["n"], "mine": r["mine"], "excluded": r["excluded"]}


# --- exclusions: threads and addresses memory must not use ---------------------


def is_excluded(con, thread_id: str, from_addr: str, to_addrs: str) -> bool:
    rules = [(r["kind"], r["value"]) for r in con.execute("SELECT kind, value FROM exclusions")]
    if not rules:
        return False
    addrs = {a.strip().lower() for a in (to_addrs or "").split(",") if a.strip()}
    addrs.add((from_addr or "").strip().lower())
    for kind, value in rules:
        if kind == "thread" and thread_id and value == thread_id:
            return True
        if kind == "address" and value in addrs:
            return True
    return False


def _apply_exclusions(con) -> None:
    """Recompute messages.excluded from the rules (after a rule is added or removed)."""
    for r in con.execute("SELECT id, thread_id, from_addr, to_addrs FROM messages"):
        con.execute("UPDATE messages SET excluded=? WHERE id=?",
                    (int(is_excluded(con, r["thread_id"], r["from_addr"], r["to_addrs"])),
                     r["id"]))
    con.commit()


def exclusion_add(con, kind: str, value: str, created_at: str = "") -> str:
    if kind not in ("thread", "address"):
        raise ValueError("kind must be thread or address")
    value = value.strip().lower() if kind == "address" else value.strip()
    if not value:
        raise ValueError("value is empty")
    r = con.execute("SELECT id FROM exclusions WHERE kind=? AND value=?", (kind, value)
                    ).fetchone()
    if r:
        return r["id"]
    xid = _uid()
    con.execute("INSERT INTO exclusions (id, kind, value, created_at) VALUES (?,?,?,?)",
                (xid, kind, value, created_at))
    _apply_exclusions(con)
    return xid


def exclusion_list(con) -> list[dict[str, Any]]:
    rows = [dict(r) for r in con.execute("SELECT * FROM exclusions ORDER BY created_at, kind")]
    for r in rows:
        if r["kind"] == "thread":
            r["messages"] = con.execute("SELECT count(*) AS n FROM messages WHERE thread_id=?",
                                        (r["value"],)).fetchone()["n"]
        else:
            r["messages"] = con.execute(
                "SELECT count(*) AS n FROM messages WHERE from_addr=? OR to_addrs LIKE ?",
                (r["value"], f"%{r['value']}%")).fetchone()["n"]
    return rows


def exclusion_delete(con, xid: str) -> None:
    con.execute("DELETE FROM exclusions WHERE id=?", (xid,))
    _apply_exclusions(con)


def mail_search(con, query: str, language: str | None = None, contact_email: str = "",
                limit: int = 5) -> list[dict[str, Any]]:
    """Paragraphs of past mail with overlapping vocabulary. Newer wins a tie,
    and mail to or from the contact being answered ranks above the rest, so
    the fact that reaches the Drafter is the latest thing said to this
    person, not the first thing ever said to anyone."""
    terms = _tokens(query)
    if not terms:
        return []
    contact_email = (contact_email or "").strip().lower()
    scored: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for r in con.execute("SELECT * FROM messages WHERE excluded=0"):
        if language and r["language"] and not r["language"].startswith(language):
            continue
        with_contact = bool(contact_email) and (
            r["from_addr"] == contact_email or contact_email in r["to_addrs"])
        offset = 0
        for para in r["text"].split("\n\n"):
            score = _score(_tokens(para), terms)
            if score:
                scored.append(((score, int(with_contact), r["date"]), {
                    "id": f"{r['id']}:{offset}",
                    "text": para.strip(),
                    "subject": r["subject"], "date": r["date"],
                    "from_addr": r["from_addr"], "from_name": r["from_name"],
                    "is_mine": bool(r["is_mine"]), "start": offset,
                    "end": offset + len(para)}))
            offset += len(para) + 2
    scored.sort(key=lambda s: s[0], reverse=True)
    return [s for _, s in scored[:limit]]


# --- embeddings: one vector per paragraph, per model ---------------------------


def embedding_put_many(con, kind: str, model: str, items: list[tuple[str, bytes, int]]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO embeddings (kind, ref, model, dim, vector) VALUES (?,?,?,?,?)",
        [(kind, ref, model, dim, vec) for ref, vec, dim in items])
    con.commit()


def embedding_refs(con, kind: str, model: str) -> set[str]:
    return {r["ref"] for r in con.execute(
        "SELECT ref FROM embeddings WHERE kind=? AND model=?", (kind, model))}


def embedding_all(con, kind: str, model: str) -> list[tuple[str, bytes]]:
    return [(r["ref"], r["vector"]) for r in con.execute(
        "SELECT ref, vector FROM embeddings WHERE kind=? AND model=?", (kind, model))]


def embedding_count(con) -> dict[str, int]:
    return {f"{r['kind']}:{r['model']}": r["n"] for r in con.execute(
        "SELECT kind, model, count(*) AS n FROM embeddings GROUP BY kind, model")}


# --- history -----------------------------------------------------------------


def history_add(con, result_json: str, rid: str, created_at: str, message: str,
                locale: str, status: str, final_text: str, contact_id: str = "") -> None:
    con.execute(
        "INSERT OR REPLACE INTO history VALUES (?,?,?,?,?,?,?,?)",
        (rid, created_at, message, locale, status, final_text, result_json, contact_id),
    )
    con.commit()


def history_delete(con, rid: str) -> None:
    con.execute("DELETE FROM history WHERE id=?", (rid,))
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
