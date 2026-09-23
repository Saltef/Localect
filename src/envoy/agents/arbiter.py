"""The Arbiter: deterministic checks that no model gets to overrule.

It does not trust the Critic to have caught everything. Glossary terms,
must-preserve items, segment coverage, and unsupported claims are verified in
code, then merged with the Critic's flags. Status follows from severity.
"""

from __future__ import annotations

from ..schemas import (
    Critique,
    Draft,
    Flag,
    FlagKind,
    LedgerEntry,
    Rewrite,
    SourceSnippet,
    Status,
)
from ..text import to_western


def _norm(text: str) -> str:
    return to_western(text).lower()


def check(draft: Draft, rewritten: Rewrite, critique: Critique, must_preserve: list[str],
          sources: list[SourceSnippet]) -> tuple[list[Flag], Status, list[LedgerEntry]]:
    flags: list[Flag] = list(critique.flags)
    final_by_id = {s.id: s.text for s in rewritten.segments}
    back_by_id = {s.id: s.text for s in critique.back_segments}
    glossary = [s.meta for s in sources if s.kind == "glossary"]

    for seg in draft.segments:
        final = final_by_id.get(seg.id)
        if final is None:
            flags.append(Flag(segment_id=seg.id, kind=FlagKind.missing_item,
                              reason="segment dropped by the rewrite", severity="block"))
            continue
        d, f = _norm(seg.text), _norm(final)
        for item in must_preserve:
            it = _norm(item)
            if it in d and it not in f:
                flags.append(Flag(segment_id=seg.id, kind=FlagKind.drifted, span=item,
                                  reason=f"'{item}' missing from the final text",
                                  severity="block"))
        for g in glossary:
            term = g["term"]
            if term.lower() in d:
                if g.get("do_not_translate") and term not in final:
                    flags.append(Flag(segment_id=seg.id, kind=FlagKind.off_glossary, span=term,
                                      reason=f"'{term}' must appear unchanged", severity="block"))
                elif g.get("rendering") and g["rendering"].lower() not in f \
                        and term.lower() not in f:
                    flags.append(Flag(segment_id=seg.id, kind=FlagKind.off_glossary, span=term,
                                      reason=f"'{term}' must be rendered as '{g['rendering']}'",
                                      severity="block"))
        for c in seg.claims:
            if not c.source_ids:
                flags.append(Flag(segment_id=seg.id, kind=FlagKind.unsupported_claim,
                                  span=c.text[:60], reason="claim has no supporting source",
                                  severity="block"))

    # Deduplicate: same segment, kind, and span means the same finding.
    seen: set[tuple[str, str, str]] = set()
    unique: list[Flag] = []
    for fl in flags:
        key = (fl.segment_id, fl.kind.value, fl.span.lower())
        if key not in seen:
            seen.add(key)
            unique.append(fl)

    if any(f.severity == "block" for f in unique):
        status = Status.escalate
    elif unique:
        status = Status.check
    else:
        status = Status.ready

    ledger = [
        LedgerEntry(
            segment_id=seg.id, draft_text=seg.text,
            final_text=final_by_id.get(seg.id, ""), back_translation=back_by_id.get(seg.id, ""),
            source_ids=[sid for c in seg.claims for sid in c.source_ids],
            flags=[f for f in unique if f.segment_id == seg.id],
        )
        for seg in draft.segments
    ]
    return unique, status, ledger


def blocking(flags: list[Flag]) -> list[Flag]:
    return [f for f in flags if f.severity == "block" and f.kind != FlagKind.unsupported_claim]
