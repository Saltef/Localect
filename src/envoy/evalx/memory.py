"""Does memory find the right message, and does the reply use the newest fact?

A fixture mailbox (``evalset/mailbox.yaml``, or ``--data`` for your own) holds
messages over several months in several languages, with facts that change.
Each question names the message holding the current answer, the value a
correct reply uses, and the values it must not use. Three numbers per model:

- retrieval: rank of the first relevant message in the token search alone and
  in the hybrid search (recall at 1, 3, 5), overall and on the cross-lingual
  questions, whose answer was said in another language than the question;
- facts: the share of replies that use the newest value (``newest``) and the
  share that use a superseded one (``stale``), after extraction by the model;
- conflicts: on questions where an older statement exists, the share of
  replies the Arbiter flagged (``conflicting_sources`` or ``stale_source``).

No prompt is tuned against these questions; the rule from docs/EVAL.md holds.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .. import db
from ..config import Settings
from ..locales import seed_locales
from ..memory import search as memsearch
from ..memory.embed import build_embedder
from ..memory.facts import extract_pending
from ..memory.index import index_all
from ..models import build_model
from ..models.stub import detect_language
from ..pipeline import PipelineError, compose
from ..schemas import ComposeRequest, FlagKind
from ..text import has_value
from ..tools import DirectTools

DEFAULT = Path(__file__).resolve().parent.parent / "evalset" / "mailbox.yaml"
KS = (1, 3, 5)


@dataclass
class Question:
    id: str
    label: str
    text: str
    locale: str
    relevant: list[str]
    newest: str = ""
    stale: list[str] = field(default_factory=list)
    contact: str = ""


@dataclass
class Mailbox:
    me: str
    messages: list[dict[str, Any]]
    questions: list[Question]


@dataclass
class MemoryScore:
    model: str
    question: str
    label: str
    language: str  # of the question
    source_language: str  # of the relevant message(s)
    cross_lingual: bool
    lexical_rank: int = 0  # 1-based rank of the first relevant message; 0 = not in top 5
    hybrid_rank: int = 0
    has_stale: bool = False
    newest_ok: bool | None = None  # None when the question fixes no value
    stale_used: bool = False
    flagged: bool = False
    status: str = ""
    error: str = ""
    seconds: float = 0.0
    reply: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and self.hybrid_rank in (1, 2, 3) and self.newest_ok is not False \
            and not self.stale_used and (self.flagged or not self.has_stale)


def load_mailbox(path: str | Path | None = None) -> Mailbox:
    raw = yaml.safe_load(Path(path or DEFAULT).read_text(encoding="utf-8"))
    qs = [Question(**q) for q in raw.get("questions", [])]
    return Mailbox(me=raw.get("me", ""), messages=list(raw.get("messages", [])), questions=qs)


def seed_mailbox(con, box: Mailbox) -> dict[str, str]:
    """Store the messages; returns fixture id -> stored id."""
    ids: dict[str, str] = {}
    for m in box.messages:
        mid = db.message_add(
            con, text=m["text"], external_id=m["id"], date=m["date"], from_addr=m["from"],
            to_addrs=",".join(m.get("to", [])), subject=m.get("subject", ""),
            is_mine=m["from"].lower() == box.me.lower(), language=detect_language(m["text"]),
            origin="fixture", source="mailbox.yaml")
        if mid is None:  # already there (a re-run on the same connection)
            r = con.execute("SELECT id FROM messages WHERE external_id=?", (m["id"],)).fetchone()
            mid = r["id"]
        ids[m["id"]] = mid
    con.commit()
    return ids


def _rank(hits: list[dict[str, Any]], wanted: set[str]) -> int:
    seen: list[str] = []
    for h in hits:
        mid = h["id"].rpartition(":")[0]
        if mid not in seen:
            seen.append(mid)
    for i, mid in enumerate(seen[:5], start=1):
        if mid in wanted:
            return i
    return 0


async def run_memory(settings: Settings, models: list[str] | None = None,
                     data: str | Path | None = None, on_row=None) -> list[MemoryScore]:
    box = load_mailbox(data)
    base = build_model(settings)
    names = models or [getattr(base, "model", base.name)]
    embedder = build_embedder(settings)
    rows: list[MemoryScore] = []
    for name in names:
        model = base.with_model(name) if hasattr(base, "with_model") and name != getattr(
            base, "model", None) else base
        con = db.connect()
        seed_locales(con)
        ids = seed_mailbox(con, box)
        index_all(con, embedder)
        await extract_pending(con, model)
        tools = DirectTools(con, embedder)
        lang_of = {m["id"]: detect_language(m["text"]) for m in box.messages}
        for q in box.questions:
            t0 = time.perf_counter()
            wanted = {ids[r] for r in q.relevant}
            qlang = detect_language(q.text)
            src_langs = {lang_of[r] for r in q.relevant}
            row = MemoryScore(model=model.name, question=q.id, label=q.label, language=qlang,
                              source_language="/".join(sorted(src_langs)),
                              cross_lingual=qlang not in src_langs, has_stale=bool(q.stale))
            row.lexical_rank = _rank(db.mail_search(con, q.text, None, q.contact, 5), wanted)
            row.hybrid_rank = _rank(memsearch.mail_search(con, embedder, q.text, None,
                                                          q.contact, 5), wanted)
            contact_id = None
            if q.contact:
                c = db.contact_by_email(con, q.contact)
                contact_id = c["id"] if c else db.contact_add(
                    con, q.contact.split("@")[0].title(), q.locale, email=q.contact)
            try:
                r = await compose(ComposeRequest(message=q.text, contact_id=contact_id),
                                  settings=settings, model=model, tools=tools, con=con)
                row.status, row.reply = r.status.value, r.final_text
                row.newest_ok = has_value(r.final_text, q.newest) if q.newest else None
                row.stale_used = any(has_value(r.final_text, v) for v in q.stale)
                row.flagged = any(f.kind in (FlagKind.conflicting_sources, FlagKind.stale_source)
                                  for f in r.flags)
            except PipelineError as e:
                row.error = str(e)[:300]
            row.seconds = round(time.perf_counter() - t0, 1)
            rows.append(row)
            if on_row:
                on_row(row)
    return rows


def summarize(rows: list[MemoryScore | dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one model's rows into the numbers the report prints."""
    rs = [r if isinstance(r, dict) else asdict(r) for r in rows]
    n = len(rs)
    cross = [r for r in rs if r["cross_lingual"]]
    valued = [r for r in rs if r["newest_ok"] is not None and not r["error"]]
    with_stale = [r for r in rs if r["has_stale"] and not r["error"]]

    def recall(subset, key):
        return {k: sum(1 for r in subset if 0 < r[key] <= k) for k in KS}

    return {
        "n": n, "errors": sum(1 for r in rs if r["error"]), "cross_lingual": len(cross),
        "lexical": recall(rs, "lexical_rank"), "hybrid": recall(rs, "hybrid_rank"),
        "lexical_cross": recall(cross, "lexical_rank"),
        "hybrid_cross": recall(cross, "hybrid_rank"),
        "valued": len(valued), "newest_ok": sum(1 for r in valued if r["newest_ok"]),
        "stale_used": sum(1 for r in valued if r["stale_used"]),
        "with_stale": len(with_stale), "flagged": sum(1 for r in with_stale if r["flagged"]),
    }


def render_memory(rows: list[MemoryScore]) -> str:
    lines = []
    by_model: dict[str, list[MemoryScore]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    for model, rs in by_model.items():
        s = summarize(rs)
        lines.append(f"\nMemory on the fixture mailbox, {model}: {s['n']} questions, "
                     f"{s['cross_lingual']} cross-lingual, {s['errors']} errors")
        lines.append(f"  {'question':8} {'lang':4} {'src':5} {'lex':>3} {'hyb':>3} "
                     f"{'newest':6} {'stale':5} {'flag':4} {'status':9} {'s':>5}")
        for r in rs:
            newest = "-" if r.newest_ok is None else ("yes" if r.newest_ok else "NO")
            lines.append(f"  {r.question:8} {r.language:4} {r.source_language:5} "
                         f"{r.lexical_rank or '-':>3} {r.hybrid_rank or '-':>3} {newest:6} "
                         f"{'USED' if r.stale_used else '-':5} "
                         f"{'yes' if r.flagged else ('-' if not r.has_stale else 'NO'):4} "
                         f"{r.status or 'ERROR':9} {r.seconds:>5}"
                         + (f"  {r.error}" if r.error else ""))
        lines.append("  retrieval, first relevant message in top k: "
                     + ", ".join(f"lexical@{k} {s['lexical'][k]}/{s['n']} · hybrid@{k} "
                                 f"{s['hybrid'][k]}/{s['n']}" for k in KS))
        if s["cross_lingual"]:
            lines.append("  cross-lingual only: "
                         + ", ".join(f"lexical@{k} {s['lexical_cross'][k]}/{s['cross_lingual']}"
                                     f" · hybrid@{k} {s['hybrid_cross'][k]}/{s['cross_lingual']}"
                                     for k in KS))
        lines.append(f"  facts: newest value used {s['newest_ok']}/{s['valued']}, stale value "
                     f"used {s['stale_used']}/{s['valued']}; conflicts flagged "
                     f"{s['flagged']}/{s['with_stale']}")
    return "\n".join(lines)


def memory_to_dicts(rows: list[MemoryScore]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rows]
