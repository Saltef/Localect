"""Reader → Drafter → Rewriter → Critic → Arbiter, with one revision loop."""

from __future__ import annotations

from . import db
from .agents import arbiter, critic, drafter, reader, rewriter
from .agents.stage import StageError
from .config import Settings
from .conventions import enforce, quiet_critic
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
from .text import strip_citations
from .tools import Tools

LANG_NAMES = {"en": "English", "ar": "Arabic", "es": "Spanish", "pt": "Portuguese",
              "fr": "French", "de": "German", "ja": "Japanese", "ru": "Russian"}


class PipelineError(RuntimeError):
    pass


# Where a message goes when the Reader cannot place it: the most widely
# spoken variety of each language, not the first configured profile in
# alphabetical order (which was es-ES over es-MX, en-GB over en-US, ar-EG
# over ar-SA). A configured contact or an explicit locale still wins.
DEFAULT_REGION = {"ar": "ar-EG", "de": "de-DE", "en": "en-US", "es": "es-MX", "fr": "fr-FR",
                  "ja": "ja-JP", "pt": "pt-BR"}


def normalize_locale_code(code: str | None) -> str:
    """"ar_eg", "AR-EG", "ar-eg" -> "ar-EG"; "es" -> "es"; junk -> ""."""
    if not code:
        return ""
    parts = [p for p in code.strip().replace("_", "-").split("-") if p]
    if not parts or not parts[0].isalpha():
        return ""
    lang = parts[0].lower()
    return f"{lang}-{parts[1].upper()}" if len(parts) > 1 and parts[1].isalnum() else lang


def locale_for_reading(con, language: str, region_guess: str | None) -> LocaleProfile | None:
    """The Reader's regional guess when it names a configured profile, else
    the language's default region, else any profile for the language."""
    language = normalize_locale_code(language).split("-")[0]
    guess = normalize_locale_code(region_guess)
    if "-" in guess:
        p = db.locale_get(con, guess)
        if p:
            return p
    default = DEFAULT_REGION.get(language)
    if default and (p := db.locale_get(con, default)):
        return p
    return db.locale_for_language(con, language)


def _fallback_locale(language: str) -> LocaleProfile:
    name = LANG_NAMES.get(language, language)
    return LocaleProfile(locale=f"{language}-XX", language=language, language_name=name,
                         region_name="unspecified", variety=name, greeting="", signoff="")


def resolve_locale(con, req: ComposeRequest, reading) -> tuple[LocaleProfile, str, str]:
    """The locale to write in, and the receiver's name and gender when a
    contact is known. An explicit locale wins, then the contact's, then the
    Reader's regional guess, then any profile for the language."""
    contact_name, gender = "", "unknown"
    if req.contact_id:
        c = db.contact_get(con, req.contact_id)
        if c:
            contact_name, gender = c["name"], c.get("gender") or "unknown"
    if req.locale:
        p = db.locale_get(con, req.locale)
        if p:
            return p, contact_name, gender
    if req.contact_id and contact_name:
        p = db.locale_get(con, db.contact_get(con, req.contact_id)["locale"])
        if p:
            return p, contact_name, gender
    p = locale_for_reading(con, reading.language, reading.region_guess)
    return (p or _fallback_locale(reading.language)), contact_name, gender


def critic_model_for(settings: Settings, model: ChatModel) -> ChatModel:
    """The Critic may run on a different model than the Drafter (``role_models``),
    so a reply is not judged by the model that wrote it."""
    name = settings.role_models.get("critic", "")
    if name and hasattr(model, "with_model") and name != getattr(model, "model", None):
        return model.with_model(name)
    return model


def polish(rw: Rewrite, locale: LocaleProfile, contact_name: str, user_name: str,
           gender: str = "unknown") -> Rewrite:
    """What the pipeline does to every rewrite before anyone judges it: strip
    leaked source ids and apply the locale's own greeting and sign-off."""
    for seg in rw.segments:
        seg.text = strip_citations(seg.text)
    enforce(rw.segments, locale, contact_name, user_name, gender=gender,
            has_claims=lambda s: False)
    return rw


async def verify(critic_model: ChatModel, d, rw: Rewrite, locale: LocaleProfile, sources,
                 must_preserve: list[str], user_language_name: str, contact_name: str,
                 user_name: str, stage_errors: list[str], gender: str = "unknown",
                 message: str = "", ablations: tuple[str, ...] | list[str] = ()):
    """Critic, then Arbiter. Returns (critique, flags, status, ledger). A Critic
    failure becomes a warning flag rather than a verdict. With the
    ``no_critic`` ablation the Arbiter judges alone."""
    try:
        if "no_critic" in ablations:
            cq = Critique(back_segments=[], flags=[])
        else:
            cq = await critic.critique(critic_model, d, rw, locale, sources, must_preserve,
                                       user_language_name, contact_name, user_name, gender)
            cq = quiet_critic(cq, {s.id: s.text for s in rw.segments}, locale, contact_name,
                              user_name, gender)
    except StageError as e:
        stage_errors.append(str(e))
        cq = Critique(back_segments=[], flags=[Flag(
            segment_id=rw.segments[0].id if rw.segments else "s1",
            kind=FlagKind.stage_failure,
            reason="the Critic could not verify this reply; read it yourself before sending",
            severity="warn")])
    flags, status, ledger = arbiter.check(d, rw, cq, must_preserve, sources, message=message)
    return cq, flags, status, ledger


async def compose(req: ComposeRequest, *, settings: Settings, model: ChatModel,
                  tools: Tools, con) -> Result:
    user_language = req.user_language or settings.user_language
    user_language_name = LANG_NAMES.get(user_language, user_language)
    stage_errors: list[str] = []
    judge = critic_model_for(settings, model)

    try:
        reading = await reader.read(model, req.message, user_language_name)
    except StageError as e:
        raise PipelineError(f"could not read the message ({e.reason})") from e

    locale, contact_name, gender = resolve_locale(con, req, reading)

    query = " ".join([reading.gloss, reading.intent, *reading.asks])
    sources = []
    sources += await tools.glossary_lookup(req.message + " " + query, locale.language)
    sources += await tools.knowledge_search(query)
    sources += await tools.history_search(query, locale.language)
    contact = db.contact_get(con, req.contact_id) if req.contact_id else None
    contact_email = (contact or {}).get("email") or ""
    # Facts and past mail are searched across languages: what was said to a
    # customer in English answers a question asked in Portuguese. History and
    # voice examples stay in the reply's language, since they carry register.
    ablations = tuple(settings.ablations)
    if "no_facts" not in ablations:
        sources += await tools.facts_search(query, None, contact_email)
    if "facts_only" not in ablations:
        sources += await tools.mail_search(query, None, contact_email)
    if req.contact_id:
        sources += await tools.thread(req.contact_id)
    voice = [] if "no_voice" in ablations else \
        await tools.voice_examples(locale.language, contact_email)

    try:
        d = await drafter.draft(model, reading, locale, sources,
                                user_language_name=user_language_name,
                                contact_name=contact_name, user_name=settings.user_name,
                                gender=gender)
    except StageError as e:
        raise PipelineError(f"could not draft a reply ({e.reason})") from e
    for seg in d.segments:
        seg.text = strip_citations(seg.text)
    enforce(d.segments, locale, contact_name, settings.user_name, gender=gender)

    async def _rewrite(flags: list[Flag] | None) -> Rewrite:
        if "no_rewriter" in ablations:
            return polish(Rewrite(segments=[RewrittenSegment(id=s.id, text=s.text)
                                            for s in d.segments]),
                          locale, contact_name, settings.user_name, gender)
        try:
            rw_ = await rewriter.rewrite(model, d, locale, sources, reading.must_preserve, flags,
                                         contact_name=contact_name, gender=gender, voice=voice)
            return polish(rw_, locale, contact_name, settings.user_name, gender)
        except StageError as e:
            stage_errors.append(str(e))
            return Rewrite(segments=[RewrittenSegment(id=s.id, text=s.text) for s in d.segments])

    async def _verify(rw: Rewrite):
        return await verify(judge, d, rw, locale, sources, reading.must_preserve,
                            user_language_name, contact_name, settings.user_name, stage_errors,
                            gender, message=req.message, ablations=ablations)

    rw = await _rewrite(None)
    cq, flags, status, ledger = await _verify(rw)
    revisions = 0

    fixable = arbiter.blocking(flags)
    if fixable and not stage_errors and "no_revision" not in ablations:
        rw = await _rewrite(fixable)
        cq, flags, status, ledger = await _verify(rw)
        revisions = 1

    if stage_errors and status == Status.ready:
        status = Status.check

    result = Result(
        message=req.message, user_language=user_language, locale=locale,
        contact_name=contact_name, contact_gender=gender, reading=reading,
        sources=sources, draft=d, rewrite=rw, critique=cq, final_text=rw.text(),
        back_translation=cq.back_translation(), status=status, flags=flags,
        suggestions=cq.suggestions, ledger=ledger,
        revisions=revisions, stage_errors=stage_errors, model=model.name,
        critic_model=judge.name if judge is not model else "",
    )
    db.history_add(con, result.model_dump_json(), result.id, result.created_at, req.message,
                   locale.locale, status.value, result.final_text, req.contact_id or "")
    return result
