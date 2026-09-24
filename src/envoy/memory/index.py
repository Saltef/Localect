"""Embed every paragraph of mail and knowledge that has no vector yet."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .. import db
from .embed import DOCUMENT, Embedder, to_bytes

KINDS = ("mail", "knowledge")


@dataclass
class Paragraph:
    kind: str
    ref: str  # "<row id>:<offset>"
    text: str


def paragraphs(con, kind: str) -> Iterator[Paragraph]:
    table = "messages" if kind == "mail" else "knowledge"
    for r in con.execute(f"SELECT id, text FROM {table}"):
        offset = 0
        for para in r["text"].split("\n\n"):
            if para.strip():
                yield Paragraph(kind, f"{r['id']}:{offset}", para.strip())
            offset += len(para) + 2


def index_all(con, embedder: Embedder, batch: int = 64,
              on_progress: Callable[[str, int, int], None] | None = None) -> dict[str, int]:
    """Embed what is missing for this embedder. Returns counts per kind."""
    done: dict[str, int] = {}
    for kind in KINDS:
        have = db.embedding_refs(con, kind, embedder.name)
        todo = [p for p in paragraphs(con, kind) if p.ref not in have]
        done[kind] = 0
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]
            vecs = embedder.embed([p.text for p in chunk], DOCUMENT)
            db.embedding_put_many(con, kind, embedder.name,
                                  [(p.ref, to_bytes(v), len(v)) for p, v in zip(chunk, vecs,
                                                                                strict=True)])
            done[kind] += len(chunk)
            if on_progress:
                on_progress(kind, done[kind], len(todo))
    return done


def index_message(con, embedder: Embedder, mid: str) -> int:
    """Embed one just-stored message (capture path)."""
    m = db.message_get(con, mid)
    if not m:
        return 0
    paras = [p for p in paragraphs(con, "mail") if p.ref.startswith(mid + ":")]
    if not paras:
        return 0
    vecs = embedder.embed([p.text for p in paras], DOCUMENT)
    db.embedding_put_many(con, "mail", embedder.name,
                          [(p.ref, to_bytes(v), len(v)) for p, v in zip(paras, vecs, strict=True)])
    return len(paras)
