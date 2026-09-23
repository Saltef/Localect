"""Starter locale profiles shipped with Envoy, loaded from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..schemas import LocaleProfile

_DIR = Path(__file__).parent


def load_starter_profiles() -> list[LocaleProfile]:
    out = []
    for f in sorted(_DIR.glob("*.yaml")):
        out.append(LocaleProfile.model_validate(yaml.safe_load(f.read_text())))
    return out


def seed_locales(con) -> int:
    """Insert starter profiles that are not already in the database."""
    from .. import db

    existing = {p.locale for p in db.locale_list(con)}
    n = 0
    for p in load_starter_profiles():
        if p.locale not in existing:
            db.locale_upsert(con, p)
            n += 1
    return n
