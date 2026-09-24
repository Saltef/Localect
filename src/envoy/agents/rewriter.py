from __future__ import annotations

from ..conventions import rendered_greeting, signoff_form
from ..models.base import ChatModel
from ..prompts import render
from ..schemas import Draft, Flag, LocaleProfile, Rewrite, SourceSnippet
from .stage import run_stage, schema_text

SYSTEM = ("You are a native editor. You make text read local without changing what it says.")


def _segments_block(draft: Draft) -> str:
    return "\n".join(f"- {s.id}: {s.text}" for s in draft.segments)


async def rewrite(model: ChatModel, draft: Draft, locale: LocaleProfile,
                  sources: list[SourceSnippet], must_preserve: list[str],
                  flags: list[Flag] | None = None, *, contact_name: str = "",
                  gender: str = "unknown") -> Rewrite:
    glossary = "\n".join(f"- {s.text}" for s in sources if s.kind == "glossary") or "- (none)"
    user = render(
        "rewriter",
        variety=locale.variety, region_name=locale.region_name, formality=locale.formality,
        date_format=locale.formats.date, currency=locale.formats.currency,
        numerals=locale.formats.numerals, must_preserve=", ".join(must_preserve) or "(none)",
        glossary=glossary, greeting=rendered_greeting(locale, contact_name, gender),
        signoff=signoff_form(locale, gender),
        notes=locale.notes, draft=_segments_block(draft), schema=schema_text(Rewrite),
    )
    if flags:
        user += "\n\nA reviewer flagged problems with your previous version. Fix each one:\n" + \
            "\n".join(f"- {f.segment_id} [{f.kind.value}] {f.reason}" for f in flags)
    context = {
        "draft": draft.model_dump(), "locale": locale.model_dump(),
        "must_preserve": must_preserve,
        "glossary": [s.meta for s in sources if s.kind == "glossary"],
        "revise": bool(flags), "flags": [f.model_dump() for f in (flags or [])],
    }
    return await run_stage(model, "rewriter", Rewrite, SYSTEM, user, context=context)
