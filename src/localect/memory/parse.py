"""Mail exports to plain records, with the standard library only.

Gmail Takeout, Apple Mail and Thunderbird export mbox; most clients save a
single message as .eml. Both are RFC 5322 and the ``email`` and ``mailbox``
modules read them."""

from __future__ import annotations

import email
import email.utils
import mailbox
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path

from .clean import clean_body


@dataclass
class ParsedMessage:
    external_id: str = ""
    thread_id: str = ""
    date: str = ""  # ISO 8601, UTC
    from_addr: str = ""
    from_name: str = ""
    to_addrs: list[str] = field(default_factory=list)
    subject: str = ""
    text: str = ""
    source: str = ""


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = email.header.decode_header(value)
    except Exception:  # noqa: BLE001 - a malformed header is still a string
        return str(value)
    out = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            out.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(raw)
    return "".join(out).strip()


def _iso(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return ""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _part_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def body_of(msg: Message) -> str:
    """The author's own words: the text/plain part when there is one, else
    the text/html part rendered to text; attachments ignored."""
    plain, html = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and not plain:
            plain = _part_text(part)
        elif ctype == "text/html" and not html:
            html = _part_text(part)
    if plain.strip():
        return clean_body(plain)
    if html.strip():
        return clean_body(html, html=True)
    return ""


def parse_message(msg: Message, source: str = "") -> ParsedMessage:
    name, addr = email.utils.parseaddr(_decode(msg.get("From")))
    tos = [a.lower() for _n, a in email.utils.getaddresses(
        [_decode(msg.get("To")), _decode(msg.get("Cc"))]) if a]
    refs = _decode(msg.get("References")).split() or _decode(msg.get("In-Reply-To")).split()
    return ParsedMessage(
        external_id=_decode(msg.get("Message-ID")).strip("<> "),
        thread_id=(refs[0].strip("<> ") if refs else _decode(msg.get("Message-ID")).strip("<> ")),
        date=_iso(msg.get("Date")),
        from_addr=addr.lower(), from_name=name, to_addrs=tos,
        subject=_decode(msg.get("Subject")), text=body_of(msg), source=source,
    )


def iter_mbox(path: Path) -> Iterator[ParsedMessage]:
    box = mailbox.mbox(str(path))
    try:
        for msg in box:
            yield parse_message(msg, source=str(path))
    finally:
        box.close()


def iter_eml(path: Path) -> Iterator[ParsedMessage]:
    with open(path, "rb") as f:
        yield parse_message(email.message_from_binary_file(f), source=str(path))


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
