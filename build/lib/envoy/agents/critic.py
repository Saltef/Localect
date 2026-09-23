from __future__ import annotations

from ..models.base import ChatModel
from ..prompts import render
from ..schemas import Critique, Draft, LocaleProfile, Rewrite, SourceSnippet
from .stage import run_stage, schema_text

SYSTEM = ("You are a skeptical bilingual proofreader. Your job is to find what changed or "
          "what is unsupported. Be exact and unsparing.")


async def critique(model: ChatModel, draft: Draft, rewritten: Rewrite, locale: LocaleProfile,
                   sources: list[SourceSnippet], must_preserve: list[str],
                   user_language_name: str) -> Critique:
    glossary = "\n".join(f"- {s.text}" for s in sources if s.kind == "glossary") or "- (none)"
    srcs = "\n".join(f"- [{s.id}] {s.text}" for s in sources if s.kind != "glossary") or "- (none)"
    user = render(
        "critic",
        variety=locale.variety, region_name=locale.region_name, formality=locale.formality,
        user_language_name=user_language_name, notes=locale.notes,
        must_preserve=", ".join(must_preserve) or "(none)", glossary=glossary, sources=srcs,
        draft="\n".join(f"- {s.id}: {s.text}" for s in draft.segments),
        final="\n".join(f"- {s.id}: {s.text}" for s in rewritten.segments),
        schema=schema_text(Critique),
    )
    context = {
        "draft": draft.model_dump(), "rewrite": rewritten.model_dump(),
        "locale": locale.model_dump(), "must_preserve": must_preserve,
        "glossary": [s.meta for s in sources if s.kind == "glossary"],
    }
    return await run_stage(model, "critic", Critique, SYSTEM, user, context=context)
