from __future__ import annotations

from ..conventions import rendered_greeting, rendered_signoff
from ..models.base import ChatModel
from ..prompts import render
from ..schemas import Critique, Draft, FlagKind, LocaleProfile, Rewrite, SourceSnippet
from .stage import run_stage, schema_text

_BLOCKING = {"drifted", "unsupported_claim", "off_glossary", "missing_item"}


def normalize_critique(raw: dict) -> dict:
    """Tolerate a model's near-misses: unknown flag kinds become suggestions,
    missing severities get the right default, odd shapes get coerced."""
    # The Arbiter alone raises the source-conflict kinds; a model naming them
    # becomes a suggestion like any other unknown kind.
    valid = {k.value for k in FlagKind} - {"conflicting_sources", "stale_source", "stage_failure",
                                         "echoed_instruction"}
    flags, suggestions = [], list(raw.get("suggestions") or [])
    for f in raw.get("flags") or []:
        if not isinstance(f, dict):
            continue
        kind = str(f.get("kind", "")).strip().lower().replace(" ", "_").replace("-", "_")
        seg = str(f.get("segment_id", "s1"))
        if kind not in valid:
            suggestions.append({"segment_id": seg,
                                "suggestion": str(f.get("reason") or f.get("suggestion") or kind)})
            continue
        f = dict(f)
        f["kind"] = kind
        f["segment_id"] = seg
        f.setdefault("span", "")
        f["severity"] = "block" if kind in _BLOCKING else "warn"
        f.setdefault("reason", kind)
        flags.append(f)
    back = []
    for b in raw.get("back_segments") or []:
        if isinstance(b, dict) and "id" in b:
            back.append({"id": str(b["id"]), "text": str(b.get("text", ""))})
    clean_sugg = [{"segment_id": str(s.get("segment_id", "s1")),
                   "suggestion": str(s.get("suggestion", ""))}
                  for s in suggestions if isinstance(s, dict) and s.get("suggestion")]
    return {"back_segments": back, "flags": flags, "suggestions": clean_sugg}

SYSTEM = ("You are a skeptical bilingual proofreader. Your job is to find what changed or "
          "what is unsupported. Be exact and unsparing.")


async def critique(model: ChatModel, draft: Draft, rewritten: Rewrite, locale: LocaleProfile,
                   sources: list[SourceSnippet], must_preserve: list[str],
                   user_language_name: str, contact_name: str = "",
                   user_name: str = "", gender: str = "unknown") -> Critique:
    glossary = "\n".join(f"- {s.text}" for s in sources if s.kind == "glossary") or "- (none)"
    srcs = "\n".join(f"- [{s.id}] {s.text}" for s in sources if s.kind != "glossary") or "- (none)"
    user = render(
        "critic",
        variety=locale.variety, region_name=locale.region_name, formality=locale.formality,
        user_language_name=user_language_name, notes=locale.notes,
        greeting=rendered_greeting(locale, contact_name, gender) or "(none)",
        signoff=rendered_signoff(locale, user_name, gender).replace("\n", " / ") or "(none)",
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
    return await run_stage(model, "critic", Critique, SYSTEM, user, context=context,
                           normalize=normalize_critique)
