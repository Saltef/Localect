"""Typed contracts for every agent's input and output, and the final Result.

Every model-driven agent emits JSON validated against one of these models.
That is what lets the deterministic stub, a local Ollama model, and a hosted
model all sit behind the same pipeline unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _uid() -> str:
    return uuid4().hex[:12]


# ----------------------------------------------------------------------------
# Locale profiles: what "sound local" means for one region.
# ----------------------------------------------------------------------------


class LocaleFormats(BaseModel):
    date: str = "YYYY-MM-DD"
    currency: str = "USD"
    numerals: str = "western"  # western | eastern-arabic


class LocaleProfile(BaseModel):
    locale: str  # e.g. "ar-EG"
    language: str  # e.g. "ar"
    language_name: str  # e.g. "Arabic"
    region_name: str  # e.g. "Egypt"
    variety: str  # e.g. "Egyptian Arabic"
    formality: str = "warm-formal"  # casual | warm-formal | formal
    greeting: str = ""
    signoff: str = ""
    formats: LocaleFormats = Field(default_factory=LocaleFormats)
    notes: str = ""
    rtl: bool = False


# ----------------------------------------------------------------------------
# Sources pulled through MCP tools.
# ----------------------------------------------------------------------------


class SourceSnippet(BaseModel):
    id: str
    kind: str  # glossary | knowledge | history | thread
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------------
# Agent outputs.
# ----------------------------------------------------------------------------


class Reading(BaseModel):
    """What the Reader understood about the incoming message."""

    language: str  # ISO 639-1, e.g. "ar"
    language_name: str = ""
    region_guess: str | None = None  # a locale code like "ar-EG" if inferable
    gloss: str  # faithful rendering in the user's language
    intent: str  # one line
    asks: list[str] = Field(default_factory=list)  # concrete things being asked
    must_preserve: list[str] = Field(default_factory=list)  # numbers, dates, names, ids
    tone: str = "neutral"


class Claim(BaseModel):
    text: str
    source_ids: list[str] = Field(default_factory=list)


class Segment(BaseModel):
    id: str
    text: str
    claims: list[Claim] = Field(default_factory=list)


class Draft(BaseModel):
    """The Drafter's grounded reply in the receiver's language."""

    language: str
    segments: list[Segment]
    notes: str = ""

    def text(self) -> str:
        return "\n\n".join(s.text for s in self.segments)


class RewriteChange(BaseModel):
    segment_id: str
    kind: str  # dialect | formality | idiom | greeting | signoff | format | cultural
    note: str


class RewrittenSegment(BaseModel):
    id: str
    text: str


class Rewrite(BaseModel):
    """The Rewriter's local-sounding version of the draft."""

    segments: list[RewrittenSegment]
    changes: list[RewriteChange] = Field(default_factory=list)

    def text(self) -> str:
        return "\n\n".join(s.text for s in self.segments)


class FlagKind(StrEnum):
    drifted = "drifted"
    tone_off = "tone_off"
    cultural_risk = "cultural_risk"
    off_glossary = "off_glossary"
    unsupported_claim = "unsupported_claim"
    missing_item = "missing_item"
    stage_failure = "stage_failure"


class Flag(BaseModel):
    segment_id: str
    kind: FlagKind
    span: str = ""
    reason: str
    severity: str = "warn"  # warn | block


class BackSegment(BaseModel):
    id: str
    text: str


class Critique(BaseModel):
    """The Critic's back-translation and flags."""

    back_segments: list[BackSegment]
    flags: list[Flag] = Field(default_factory=list)

    def back_translation(self) -> str:
        return "\n\n".join(s.text for s in self.back_segments)


class Status(StrEnum):
    ready = "ready"
    check = "check"
    escalate = "escalate"


class LedgerEntry(BaseModel):
    segment_id: str
    draft_text: str
    final_text: str
    back_translation: str
    source_ids: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)


class Result(BaseModel):
    id: str = Field(default_factory=_uid)
    created_at: str = Field(default_factory=_now)
    message: str
    user_language: str
    locale: LocaleProfile
    reading: Reading
    sources: list[SourceSnippet]
    draft: Draft
    rewrite: Rewrite
    critique: Critique
    final_text: str
    back_translation: str
    status: Status
    flags: list[Flag]
    ledger: list[LedgerEntry]
    revisions: int = 0
    stage_errors: list[str] = Field(default_factory=list)
    model: str = ""


class ComposeRequest(BaseModel):
    message: str
    locale: str | None = None  # override the Reader's guess
    contact_id: str | None = None
    user_language: str | None = None  # defaults to settings
    model: str | None = None  # per-request override of the configured model name


class ComposeResponse(BaseModel):
    result: Result
