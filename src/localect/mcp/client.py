"""Spawns Localect's MCP servers once and exposes them behind the Tools interface."""

from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client

from ..tools import (
    fact_snippets,
    glossary_snippets,
    history_snippets,
    knowledge_snippets,
    mail_snippets,
    thread_snippets,
)
from .servers import SERVERS


def _payload(result) -> Any:
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict) and "result" in sc:
        return sc["result"]
    text = "\n".join(c.text for c in result.content if getattr(c, "text", None))
    return json.loads(text) if text else None


class MCPTools:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = str(db_path)
        self._stack: AsyncExitStack | None = None
        self.sessions: dict[str, ClientSession] = {}

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        env = {**get_default_environment(),
               **{k: v for k, v in os.environ.items() if k.startswith("LOCALECT_")},
               "LOCALECT_DB": self.db_path}
        for name in SERVERS:
            params = StdioServerParameters(
                command=sys.executable, args=["-m", f"localect.mcp.servers.{name}"], env=env
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[name] = session

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self.sessions = {}

    async def _call(self, server: str, tool: str, **args) -> Any:
        result = await self.sessions[server].call_tool(tool, args)
        return _payload(result) or []

    async def glossary_lookup(self, text, language):
        rows = await self._call("glossary", "lookup", text=text, language=language)
        return glossary_snippets(rows)

    async def knowledge_search(self, query):
        return knowledge_snippets(await self._call("knowledge", "search", query=query))

    async def history_search(self, query, language):
        return history_snippets(
            await self._call("history", "search_past", query=query, language=language)
        )

    async def thread(self, contact_id):
        return thread_snippets(await self._call("thread", "get_thread", contact_id=contact_id))

    async def mail_search(self, query, language, contact_email):
        return mail_snippets(await self._call("mail", "search_mail", query=query,
                                              language=language, contact_email=contact_email))

    async def facts_search(self, query, language, contact_email):
        return fact_snippets(await self._call("mail", "search_facts", query=query,
                                              language=language, contact_email=contact_email))

    async def voice_examples(self, language, contact_email):
        return await self._call("mail", "voice_examples", language=language,
                                contact_email=contact_email)

    async def list_tools(self) -> dict[str, list[str]]:
        out = {}
        for name, s in self.sessions.items():
            out[name] = [t.name for t in (await s.list_tools()).tools]
        return out
