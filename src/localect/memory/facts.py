"""Extract dated facts from stored messages, and make them comparable.

A topic key is the alias-folded token set of the topic, so "return window",
"prazo de devolução" and "مدة الاسترجاع" compare equal when the alias table
knows the words. Values are compared after digit-script normalisation."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass

from .. import db
from ..agents.extractor import extract
from ..agents.stage import StageError
from ..models.base import ChatModel
from ..text import to_western, tokens
from .parse import now_iso


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", to_western(text).lower()).split())


def verify_provenance(statement: str, text: str) -> bool:
    """Is the statement really in the message? A fact whose wording cannot be
    found in its source is a model's paraphrase or invention and is not
    stored. Exact after normalising case, punctuation and digit script; else
    every content word of the statement must occur in the message (a model
    that trims a clause still passes; one that adds a number does not)."""
    st, src = _norm(statement), _norm(text)
    if not st:
        return False
    if st in src:
        return True
    words = [w for w in st.split() if len(w) > 2 or w.isdigit()]
    have = set(src.split())
    return bool(words) and all(w in have for w in words)


def topic_key(topic: str) -> str:
    return " ".join(sorted(tokens(topic))) or topic.strip().lower()


def value_key(value: str) -> str:
    """"30 days", "30", "٣٠ يوم" and "30 dias" are one value: when a value has
    numbers, the numbers are the key; otherwise its normalised text."""
    from ..text import numbers

    nums = numbers(value)
    if nums:
        return " ".join(sorted(nums))
    return " ".join(to_western(value).lower().split())


@dataclass
class ExtractReport:
    messages: int = 0
    facts: int = 0
    failed: int = 0
    unverified: int = 0  # statements the model gave that are not in the message


async def extract_message(con, model: ChatModel, m: dict,
                          report: ExtractReport | None = None) -> int:
    """Run the Extractor on one stored message; store the facts whose wording
    is verifiably in the message; mark it read."""
    who = "you" if m["is_mine"] else (m["from_name"] or m["from_addr"] or "them")
    ex = await extract(model, m["text"], who=who, when=(m["date"] or "")[:10],
                       subject=m["subject"])
    # The other side of the exchange: who the fact was said to, or by.
    party = (m["to_addrs"].split(",")[0] if m["is_mine"] else m["from_addr"]) or ""
    n = 0
    for f in ex.facts:
        if not verify_provenance(f.statement, m["text"]):
            if report is not None:
                report.unverified += 1
            continue
        db.fact_add(con, topic=f.topic, topic_key=topic_key(f.topic), statement=f.statement,
                    value=f.value, said_on=m["date"], said_by="you" if m["is_mine"] else "them",
                    party=party, message_id=m["id"], language=m["language"],
                    created_at=now_iso())
        n += 1
    db.message_mark_extracted(con, m["id"], now_iso())
    con.commit()
    return n


async def extract_pending(con, model: ChatModel, limit: int = 1000,
                          on_message: Callable[[dict, int], None] | None = None) -> ExtractReport:
    report = ExtractReport()
    for m in db.messages_unextracted(con, limit):
        try:
            n = await extract_message(con, model, m, report)
        except StageError:
            report.failed += 1
            continue
        report.messages += 1
        report.facts += n
        if on_message:
            on_message(m, n)
    return report


def extract_pending_sync(con, model: ChatModel, limit: int = 1000, on_message=None
                         ) -> ExtractReport:
    return asyncio.run(extract_pending(con, model, limit, on_message))
