"""Envoy's built-in MCP servers. Each runs on stdio and reads ENVOY_DB."""

from __future__ import annotations

import os
from pathlib import Path

from ... import db


def open_db():
    path = os.environ.get("ENVOY_DB", "")
    return db.connect(Path(path) if path else ":memory:")


SERVERS = ["glossary", "knowledge", "history", "thread", "mail"]
