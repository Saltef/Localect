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
                  gender: str = "unknown", voice: list[dict] | None = None) -> Rewrite:
    glossary = "\n".join(f"- {s.text}" for s in sources if s.kind == "glossary") or "- (none)"
    voice_block = "\n\n".join(
        f"[{(v.get('date') or '')[:10]}] {v['text']}" for v in (voice or []) if v.get("text")
    ) or "(none on file)"
    user = render(
        "rewriter",
        variety=locale.variety, region_name=locale.region_name, formality=locale.formality,
        date_format=locale.formats.date, currency=locale.formats.currency,
        numerals=locale.formats.numerals, must_preserve=", ".join(must_preserve) or "(none)",
        glossary=glossary, greeting=rendered_greeting(locale, contact_name, gender),
        signoff=signoff_form(locale, gender),
        notes=locale.notes, draft=_segments_block(draft), schema=schema_text(Rewrite),
        voice=voice_block,
    )
    if flags:
        user += ("\n\nA reviewer blocked your previous version for the reasons below. "
                 "This is not optional: every one must be fixed, even where that means "
                 "removing content rather than rewording it. The reply will be rejected "
                 "again if any of them are not fixed:\n") + \
            "\n".join(f"- {f.segment_id} [{f.kind.value}] {f.reason}" for f in flags)
    context = {
        "draft": draft.model_dump(), "locale": locale.model_dump(),
        "must_preserve": must_preserve,
        "glossary": [s.meta for s in sources if s.kind == "glossary"],
        "revise": bool(flags), "flags": [f.model_dump() for f in (flags or [])],
        "voice": voice or [],
    }
    return await run_stage(model, "rewriter", Rewrite, SYSTEM, user, context=context)
