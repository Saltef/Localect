"""Deterministic locale conventions.

The locale profile's greeting and sign-off are the user's configured
convention. Models are asked to use them, but a model that improvises ("Hi
Safea," for an unknown customer, "أهلاً عميلنا العزيز،" for Egypt) should not
be able to override them, so they are applied in code after every stage. The
same rule keeps the Critic from flagging the convention itself.
"""

from __future__ import annotations

import re

from .schemas import Critique, LocaleProfile
from .text import fill_name

_MAX_WORDS = 8


def rendered_greeting(locale: LocaleProfile, contact_name: str) -> str:
    return fill_name(locale.greeting, contact_name, locale.language)


def rendered_signoff(locale: LocaleProfile, user_name: str) -> str:
    base = locale.signoff.strip()
    if not base:
        return ""
    return f"{base}\n{user_name}" if user_name else base


def _short(text: str) -> bool:
    return len(re.findall(r"\S+", text)) <= _MAX_WORDS


def _norm(text: str) -> str:
    return re.sub(r"[\s,،.。!:]+", " ", text).strip().lower()


def enforce(segments, locale: LocaleProfile, contact_name: str, user_name: str,
            *, has_claims=lambda s: bool(getattr(s, "claims", None))) -> list[str]:
    """Replace a short, claim-free first/last segment with the locale's own
    greeting / sign-off. Returns the ids of segments that were changed."""
    changed: list[str] = []
    if not segments:
        return changed
    g = rendered_greeting(locale, contact_name)
    first = segments[0]
    if g and _short(first.text) and not has_claims(first) and _norm(first.text) != _norm(g):
        first.text = g
        changed.append(first.id)
    s = rendered_signoff(locale, user_name)
    last = segments[-1]
    if s and len(segments) > 1 and _short(last.text) and not has_claims(last) \
            and _norm(last.text) != _norm(s):
        last.text = s
        changed.append(last.id)
    return changed


def quiet_critic(cq: Critique, final_by_id: dict[str, str], locale: LocaleProfile,
                 contact_name: str, user_name: str) -> Critique:
    """Drop flags and suggestions aimed at the locale's own conventions, and
    suggestions that merely repeat the text they are attached to."""
    conventions = {_norm(rendered_greeting(locale, contact_name)),
                   _norm(rendered_signoff(locale, user_name))}
    conventions.discard("")

    def is_convention(seg_id: str) -> bool:
        return _norm(final_by_id.get(seg_id, "")) in conventions

    cq.flags = [f for f in cq.flags if not (is_convention(f.segment_id) and f.severity == "warn")]
    cq.suggestions = [
        s for s in cq.suggestions
        if not is_convention(s.segment_id)
        and _norm(s.suggestion) != _norm(final_by_id.get(s.segment_id, ""))
    ]
    return cq
