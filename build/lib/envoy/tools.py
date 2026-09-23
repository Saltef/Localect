"""The tool interface the agents use, and a direct (in-process) implementation.

``MCPTools`` in ``envoy.mcp.client`` implements the same interface over real
MCP servers. ``DirectTools`` hits the database in-process and exists for fast
tests and for the CLI demo.
"""

from __future__ import annotations

from typing import Protocol

from . import db
from .schemas import SourceSnippet


class Tools(Protocol):
    async def glossary_lookup(self, text: str, language: str) -> list[SourceSnippet]: ...
    async def knowledge_search(self, query: str) -> list[SourceSnippet]: ...
    async def history_search(self, query: str, language: str | None) -> list[SourceSnippet]: ...
    async def thread(self, contact_id: str) -> list[SourceSnippet]: ...


def glossary_snippets(rows: list[dict]) -> list[SourceSnippet]:
    out = []
    for g in rows:
        rule = "do not translate" if g.get("do_not_translate") else f"render as '{g['rendering']}'"
        out.append(SourceSnippet(id=f"gl:{g['id']}", kind="glossary",
                                 text=f"{g['term']}: {rule}", meta=g))
    return out


def knowledge_snippets(rows: list[dict]) -> list[SourceSnippet]:
    return [SourceSnippet(id=f"kb:{r['id']}", kind="knowledge", text=r["text"],
                          meta={"title": r["title"], "start": r["start"], "end": r["end"]})
            for r in rows]


def history_snippets(rows: list[dict]) -> list[SourceSnippet]:
    return [SourceSnippet(id=f"hx:{r['id']}", kind="history", text=r["final_text"],
                          meta={"message": r["message"], "locale": r["locale"]}) for r in rows]


def thread_snippets(rows: list[dict]) -> list[SourceSnippet]:
    return [SourceSnippet(id=f"th:{r['id']}", kind="thread",
                          text=f"They wrote: {r['message']}\nWe replied: {r['final_text']}",
                          meta={"created_at": r["created_at"]}) for r in rows]


class DirectTools:
    def __init__(self, con) -> None:
        self.con = con

    async def glossary_lookup(self, text, language):
        return glossary_snippets(db.glossary_lookup(self.con, text, language))

    async def knowledge_search(self, query):
        return knowledge_snippets(db.knowledge_search(self.con, query))

    async def history_search(self, query, language):
        return history_snippets(db.history_search(self.con, query, language))

    async def thread(self, contact_id):
        return thread_snippets(db.history_thread(self.con, contact_id))
