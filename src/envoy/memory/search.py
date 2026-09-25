"""Hybrid retrieval: the token search and the vector search, fused.

Each ranking sees things the other misses. Token overlap finds exact ids,
numbers and names; vectors find "prazo de devolução" when the policy says
"return window". Reciprocal rank fusion needs no score calibration between
the two, and the priors that matter for mail (the contact being answered,
then the newest statement) are applied after fusion."""

from __future__ import annotations

from typing import Any

from .. import db
from .embed import QUERY, Embedder, HashEmbedder, dot, from_bytes
from .index import index_all

RRF_K = 60


def ensure_indexed(con, embedder: Embedder) -> None:
    """The offline embedder is cheap, so it indexes whatever is missing at
    search time; a remote one is only run by ``envoy index`` and the import
    and capture paths, so searching never spends API calls."""
    if isinstance(embedder, HashEmbedder):
        index_all(con, embedder)


def _vector_rank(con, embedder: Embedder, kind: str, query: str, limit: int) -> list[str]:
    stored = db.embedding_all(con, kind, embedder.name)
    if not stored:
        return []
    q = embedder.embed([query], QUERY)[0]
    scored = [(dot(q, from_bytes(raw)), ref) for ref, raw in stored]
    scored.sort(reverse=True)
    return [ref for score, ref in scored[:limit] if score > 0]


def _mail_row(con, ref: str, contact_email: str) -> dict[str, Any] | None:
    mid, _, offset = ref.rpartition(":")
    m = db.message_get(con, mid)
    if not m or m.get("excluded"):
        return None
    start = int(offset)
    para = m["text"][start:].split("\n\n", 1)[0]
    return {"id": ref, "text": para.strip(), "subject": m["subject"], "date": m["date"],
            "from_addr": m["from_addr"], "from_name": m["from_name"],
            "is_mine": bool(m["is_mine"]), "start": start, "end": start + len(para),
            "language": m["language"],
            "with_contact": bool(contact_email) and (
                m["from_addr"] == contact_email or contact_email in m["to_addrs"])}


def _knowledge_row(con, ref: str) -> dict[str, Any] | None:
    kid, _, offset = ref.rpartition(":")
    r = con.execute("SELECT title, text FROM knowledge WHERE id=?", (kid,)).fetchone()
    if not r:
        return None
    start = int(offset)
    para = r["text"][start:].split("\n\n", 1)[0]
    return {"id": ref, "title": r["title"], "text": para.strip(), "start": start,
            "end": start + len(para)}


def _fuse(rankings: list[list[str]]) -> dict[str, float]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, ref in enumerate(ranking):
            fused[ref] = fused.get(ref, 0.0) + 1.0 / (RRF_K + rank + 1)
    return fused


def mail_search(con, embedder: Embedder | None, query: str, language: str | None = None,
                contact_email: str = "", limit: int = 5) -> list[dict[str, Any]]:
    """Token search fused with vector search, then contact first, newest first.
    Without an embedder this is the token search alone."""
    contact_email = (contact_email or "").strip().lower()
    lexical = [r["id"] for r in db.mail_search(con, query, language, contact_email, limit=50)]
    if embedder is None:
        rankings = [lexical]
    else:
        ensure_indexed(con, embedder)
        rankings = [lexical, _vector_rank(con, embedder, "mail", query, 50)]
    fused = _fuse(rankings)
    rows = []
    for ref, score in fused.items():
        row = _mail_row(con, ref, contact_email)
        if row is None:
            continue
        if language and row["language"] and not row["language"].startswith(language):
            continue
        rows.append((score, row))
    rows.sort(key=lambda s: (s[0], s[1]["with_contact"], s[1]["date"]), reverse=True)
    out = []
    for _score, row in rows[:limit]:
        row.pop("with_contact", None)
        row.pop("language", None)
        out.append(row)
    return out


def knowledge_search(con, embedder: Embedder | None, query: str, limit: int = 5
                     ) -> list[dict[str, Any]]:
    lexical = [r["id"] for r in db.knowledge_search(con, query, limit=50)]
    if embedder is None:
        rankings = [lexical]
    else:
        ensure_indexed(con, embedder)
        rankings = [lexical, _vector_rank(con, embedder, "knowledge", query, 50)]
    fused = _fuse(rankings)
    # Keep the lexical order on ties so the stub's tie-break (earlier paragraph
    # wins) still holds when vectors add nothing.
    order = {ref: i for i, ref in enumerate(lexical)}
    ranked = sorted(fused, key=lambda ref: (-fused[ref], order.get(ref, 10**6)))
    rows = [r for r in (_knowledge_row(con, ref) for ref in ranked[:limit]) if r]
    return rows
