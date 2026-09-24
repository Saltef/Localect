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
_MAX_CHARS = 20  # for scripts written without spaces (Japanese, Chinese, Korean)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff66-\uff9f]")

# Closings a model tends to emit as separate short segments, across languages.
_CLOSING = re.compile(
    r"(regards|sincerely|best|cheers|thanks|thank you|cordialement|salutations|saludos|"
    r"atenciosamente|abraços|abracos|cumprimentos|grüßen|gruessen|freundlich|تحيات|تقبل|"
    r"شكر|مع خالص|よろしく|敬具)",
    re.IGNORECASE,
)


def _closing_like(text: str, user_name: str, signoff: str) -> bool:
    n = _norm(text)
    if not n:
        return True
    if user_name and n == _norm(user_name):
        return True
    if signoff and (n == _norm(signoff) or n.startswith(_norm(signoff.split()[0]))):
        return True
    if bool(_CLOSING.search(text)) and _short(text):
        return True
    return _chars(n) <= 6 if _CJK.search(text) else len(n.split()) <= 2


GENDERS = ("unknown", "female", "male")


def greeting_form(locale: LocaleProfile, gender: str = "unknown") -> str:
    """The template for this receiver: a gendered variant when the language
    inflects address and the gender is known, else the neutral form."""
    return locale.greetings.get(gender) or locale.greeting


def signoff_form(locale: LocaleProfile, gender: str = "unknown") -> str:
    return locale.signoffs.get(gender) or locale.signoff


def rendered_greeting(locale: LocaleProfile, contact_name: str, gender: str = "unknown") -> str:
    return fill_name(greeting_form(locale, gender), contact_name, locale.language)


def rendered_signoff(locale: LocaleProfile, user_name: str, gender: str = "unknown") -> str:
    base = signoff_form(locale, gender).strip()
    if not base:
        return ""
    return f"{base}\n{user_name}" if user_name else base


def _chars(text: str) -> int:
    """Letters only: what a length limit should count in a script without spaces."""
    return len(re.findall(r"\w", text))


def _short(text: str) -> bool:
    """Short enough to be a greeting or a sign-off rather than a sentence of
    the reply. A segment that carries a number is never one: replacing it
    would drop a fact. Japanese has no word spaces, so it is measured in
    characters, not whitespace tokens."""
    if re.search(r"\d", text):
        return False
    if _CJK.search(text):
        return _chars(text) <= _MAX_CHARS
    return len(re.findall(r"\S+", text)) <= _MAX_WORDS


def _norm(text: str) -> str:
    return re.sub(r"[\s,،.。!:]+", " ", text).strip().lower()


def enforce(segments, locale: LocaleProfile, contact_name: str, user_name: str,
            *, gender: str = "unknown",
            has_claims=lambda s: bool(getattr(s, "claims", None))) -> list[str]:
    """Replace a short, claim-free first/last segment with the locale's own
    greeting / sign-off. Returns the ids of segments that were changed."""
    changed: list[str] = []
    if not segments:
        return changed
    g = rendered_greeting(locale, contact_name, gender)
    first = segments[0]
    if g and _short(first.text) and not has_claims(first) and _norm(first.text) != _norm(g):
        first.text = g
        changed.append(first.id)
    s = rendered_signoff(locale, user_name, gender)
    if s and len(segments) > 1:
        # Walk back over the trailing run of short, claim-free, closing-like segments.
        i = len(segments)
        while i > 1 and _short(segments[i - 1].text) and not has_claims(segments[i - 1]) \
                and _closing_like(segments[i - 1].text, user_name, signoff_form(locale, gender)):
            i -= 1
        tail = segments[i:]
        if tail:
            keep = tail[0]
            if keep.text != s or len(tail) > 1:
                keep.text = s
                changed.append(keep.id)
            del segments[i + 1:]
    return changed


def quiet_critic(cq: Critique, final_by_id: dict[str, str], locale: LocaleProfile,
                 contact_name: str, user_name: str, gender: str = "unknown") -> Critique:
    """Drop flags and suggestions aimed at the locale's own conventions, and
    suggestions that merely repeat the text they are attached to."""
    conventions = {_norm(rendered_greeting(locale, contact_name, gender)),
                   _norm(rendered_signoff(locale, user_name, gender)),
                   _norm(signoff_form(locale, gender))}
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
