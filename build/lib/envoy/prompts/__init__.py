"""Prompt templates, one file per agent, with {{name}} placeholders."""

from __future__ import annotations

import re
from pathlib import Path

_DIR = Path(__file__).parent
_PH = re.compile(r"\{\{(\w+)\}\}")


def load(name: str) -> str:
    return (_DIR / f"{name}.md").read_text()


def render(name: str, **vars: object) -> str:
    template = load(name)

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in vars:
            raise KeyError(f"prompt {name!r} needs {key!r}")
        return str(vars[key])

    return _PH.sub(sub, template)
