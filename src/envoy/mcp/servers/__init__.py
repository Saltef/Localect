"""Envoy's built-in MCP servers. Each runs on stdio and reads ENVOY_DB."""

from __future__ import annotations

import os
from pathlib import Path

from ... import db


def open_db():
    path = os.environ.get("ENVOY_DB", "")
    return db.connect(Path(path) if path else ":memory:")


def open_embedder():
    """The embedder the user's settings imply (ENVOY_* variables win, as in
    the main process). Servers are spawned with those variables passed on."""
    from ...config import Settings
    from ...memory.embed import build_embedder

    return build_embedder(Settings.load())


SERVERS = ["glossary", "knowledge", "history", "thread", "mail"]
