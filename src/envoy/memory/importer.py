"""Walk files and folders; store mail as messages and documents as knowledge."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .. import db
from ..models.stub import detect_language
from .parse import ParsedMessage, iter_eml, iter_mbox

MAIL_SUFFIXES = {".mbox", ".eml"}
DOC_SUFFIXES = {".md", ".txt", ".markdown"}
PDF_SUFFIX = ".pdf"


@dataclass
class ImportReport:
    messages: int = 0
    mine: int = 0
    duplicates: int = 0
    empty: int = 0
    documents: int = 0
    files: int = 0
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.files} file(s)", f"{self.messages} message(s) stored "
                 f"({self.mine} written by you)"]
        if self.duplicates:
            parts.append(f"{self.duplicates} already stored")
        if self.empty:
            parts.append(f"{self.empty} with no text")
        if self.documents:
            parts.append(f"{self.documents} document(s) added to the knowledge base")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        return ", ".join(parts)


def _is_mbox(path: Path) -> bool:
    if path.suffix.lower() == ".mbox":
        return True
    if path.suffix:
        return False
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"From "
    except OSError:
        return False


_HEADER = re.compile(rb"^(Message-ID|From|Date|Subject|To|Received|Return-Path|X-[A-Za-z-]+):",
                     re.IGNORECASE)


def _is_rfc822(path: Path) -> bool:
    """A raw message file with no extension, as maildir exports and the Enron
    corpus store them (the file starts with header lines)."""
    if path.suffix and path.suffix.lower() != ".eml":
        return path.suffix.lower() == ".eml"
    try:
        with open(path, "rb") as f:
            head = f.read(2048)
    except OSError:
        return False
    if head.startswith(b"From "):
        return False  # mbox
    lines = head.split(b"\n")[:5]
    return sum(1 for ln in lines if _HEADER.match(ln)) >= 2


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # optional: pip install pypdf
    except ImportError as e:
        raise RuntimeError("PDF import needs the pypdf package: pip install pypdf") from e
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()


def store_message(con, m: ParsedMessage, my_addresses: set[str], origin: str = "import",
                  report: ImportReport | None = None) -> str | None:
    report = report if report is not None else ImportReport()
    if not m.text.strip():
        report.empty += 1
        return None
    mine = m.from_addr in my_addresses
    mid = db.message_add(
        con, text=m.text, external_id=m.external_id, thread_id=m.thread_id, date=m.date,
        from_addr=m.from_addr, from_name=m.from_name, to_addrs=",".join(m.to_addrs),
        subject=m.subject, is_mine=mine, language=detect_language(m.text), origin=origin,
        source=m.source)
    if mid is None:
        report.duplicates += 1
        return None
    report.messages += 1
    report.mine += int(mine)
    return mid


def _files(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        if p.is_dir():
            yield from sorted(q for q in p.rglob("*") if q.is_file())
        else:
            yield p


def import_paths(con, paths: Iterable[str | Path], my_addresses: Iterable[str] = (),
                 on_file: Callable[[Path, ImportReport], None] | None = None) -> ImportReport:
    """Import every mbox, .eml, Markdown, text and PDF file under the paths.
    ``my_addresses`` marks which messages the user wrote."""
    mine = {a.strip().lower() for a in my_addresses if a.strip()}
    report = ImportReport()
    for path in _files(Path(p) for p in paths):
        suffix = path.suffix.lower()
        try:
            if _is_mbox(path):
                for m in iter_mbox(path):
                    store_message(con, m, mine, report=report)
            elif suffix == ".eml" or (not suffix and _is_rfc822(path)):
                for m in iter_eml(path):
                    store_message(con, m, mine, report=report)
            elif suffix in DOC_SUFFIXES:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    db.knowledge_add(con, path.stem, text)
                    report.documents += 1
            elif suffix == PDF_SUFFIX:
                text = _pdf_text(path)
                if text:
                    db.knowledge_add(con, path.stem, text)
                    report.documents += 1
            else:
                report.skipped.append(str(path))
                continue
        except (OSError, RuntimeError, UnicodeDecodeError) as e:
            report.skipped.append(f"{path}: {e}")
            continue
        report.files += 1
        con.commit()
        if on_file:
            on_file(path, report)
    con.commit()
    return report
