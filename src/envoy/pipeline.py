"""Reader → Drafter → Rewriter → Critic → Arbiter, with one revision loop."""

from __future__ import annotations

from . import db
from .agents import arbiter, critic, drafter, reader, rewriter
from .agents.stage import StageError
from .config import Settings
from .models.base import ChatModel
from .schemas import (
    ComposeRequest,
    Critique,
    Flag,
    FlagKind,
    LocaleProfile,
    Result,
    Rewrite,
    RewrittenSegment,
    Status,
)
from .tools import Tools

LANG_NAMES = {"en": "English", "ar": "Arabic", "es": "Spanish", "pt": "Portuguese",
              "fr": "French", "de": "German", "ja": "Japanese", "ru": "Russian"}


class PipelineError(RuntimeError):
    pass


def _fallback_locale(language: str) -> LocaleProfile:
    name = LANG_NAMES.get(language, language)
    return LocaleProfile(locale=f"{language}-XX", language=language, language_name=name,
                         region_name="unspecified", variety=name, greeting="", signoff="")


def resolve_locale(con, req: ComposeRequest, reading) -> tuple[LocaleProfile, str]:
    if req.locale:
        p = db.locale_get(con, req.locale)
        if p:
            return p, ""
    contact_name = ""
    if req.contact_id:
        c = db.contact_get(con, req.contact_id)
        if c:
            contact_name = c["name"]
            p = db.locale_get(con, c["locale"])
            if p:
                return p, contact_name
    if reading.region_guess:
        p = db.locale_get(con, reading.region_guess)
        if p:
            return p, contact_name
    p = db.locale_for_language(con, reading.language)
    return (p or _fallback_locale(reading.language)), contact_name


async def compose(req: ComposeRequest, *, settings: Settings, model: ChatModel,
                  tools: Tools, con) -> Result:
    user_language = req.user_language or settings.user_language
    user_language_name = LANG_NAMES.get(user_language, user_language)
    stage_errors: list[str] = []

    try:
        reading = await reader.read(model, req.message, user_language_name)
    except StageError as e:
        raise PipelineError(f"could not read the message ({e.reason})") from e

    locale, contact_name = resolve_locale(con, req, reading)

    query = " ".join([reading.gloss, reading.intent, *reading.asks])
    sources = []
    sources += await tools.glossary_lookup(req.message + " " + query, locale.language)
    sources += await tools.knowledge_search(query)
    sources += await tools.history_search(query, locale.language)
    if req.contact_id:
        sources += await tools.thread(req.contact_id)

    try:
        d = await drafter.draft(model, reading, locale, sources,
                                user_language_name=user_language_name,
                                contact_name=contact_name, user_name=settings.user_name)
    except StageError as e:
        raise PipelineError(f"could not draft a reply ({e.reason})") from e

    async def _rewrite(flags: list[Flag] | None) -> Rewrite:
        try:
            return await rewriter.rewrite(model, d, locale, sources, reading.must_preserve, flags)
        except StageError as e:
            stage_errors.append(str(e))
            return Rewrite(segments=[RewrittenSegment(id=s.id, text=s.text) for s in d.segments])

    async def _critique(rw: Rewrite) -> Critique:
        try:
            return await critic.critique(model, d, rw, locale, sources, reading.must_preserve,
                                         user_language_name)
        except StageError as e:
            stage_errors.append(str(e))
            return Critique(back_segments=[], flags=[Flag(
                segment_id=rw.segments[0].id if rw.segments else "s1",
                kind=FlagKind.stage_failure, reason="critic failed; unverified",
                severity="block")])

    rw = await _rewrite(None)
    cq = await _critique(rw)
    flags, status, ledger = arbiter.check(d, rw, cq, reading.must_preserve, sources)
    revisions = 0

    fixable = arbiter.blocking(flags)
    if fixable and not stage_errors:
        rw = await _rewrite(fixable)
        cq = await _critique(rw)
        flags, status, ledger = arbiter.check(d, rw, cq, reading.must_preserve, sources)
        revisions = 1

    if stage_errors and status != Status.escalate:
        status = Status.escalate

    result = Result(
        message=req.message, user_language=user_language, locale=locale, reading=reading,
        sources=sources, draft=d, rewrite=rw, critique=cq, final_text=rw.text(),
        back_translation=cq.back_translation(), status=status, flags=flags, ledger=ledger,
        revisions=revisions, stage_errors=stage_errors, model=model.name,
    )
    db.history_add(con, result.model_dump_json(), result.id, result.created_at, req.message,
                   locale.locale, status.value, result.final_text, req.contact_id or "")
    return result
