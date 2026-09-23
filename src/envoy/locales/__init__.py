"""Starter locale profiles shipped with Envoy, loaded from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..schemas import LocaleProfile

_DIR = Path(__file__).parent


def load_starter_profiles() -> list[LocaleProfile]:
    out = []
    for f in sorted(_DIR.glob("*.yaml")):
        out.append(LocaleProfile.model_validate(yaml.safe_load(f.read_text(encoding="utf-8"))))
    return out


def seed_locales(con) -> int:
    """Insert missing starter profiles and refresh unedited ones.

    A profile the user has edited (origin 'user') is never touched. Starter
    profiles are updated in place when Envoy ships a better version.
    """
    from .. import db

    n = 0
    for p in load_starter_profiles():
        origin = db.locale_origin(con, p.locale)
        if origin == "user":
            continue
        current = db.locale_get(con, p.locale)
        if current is None or current != p:
            db.locale_upsert(con, p, origin="starter")
            n += 1
    return n
