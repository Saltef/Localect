"""Replay your own inbox: the test on actual data.

Every stored exchange where someone wrote to you and you replied is a test
case that needed no writing: the incoming message is the input, and the reply
you actually sent is the reference. Envoy composes a reply to the incoming
message while its memory is limited to what existed before that moment, so
it cannot simply retrieve your answer. Then, per pair:

- facts: the numbers in your real reply (amounts, days, ids) that Envoy's
  reply also states; a number in Envoy's reply that yours does not have is
  counted too, since it is either invented or from a different fact;
- language: Envoy replied in the language you replied in;
- closeness: chrF between Envoy's reply and yours (a rough proxy for voice
  and content; 100 is identical, anything above the low 30s is the same
  message said differently);
- status: what the Arbiter concluded, and whether it errored.

Nothing here is a benchmark against a known answer set; it is the pipeline
against your own history, which is the only actual data there is."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from .. import db
from ..config import Settings
from ..memory.embed import build_embedder
from ..models import build_model
from ..models.stub import detect_language
from ..pipeline import PipelineError, compose
from ..schemas import ComposeRequest
from ..text import numbers
from ..tools import DirectTools
from .flores import chrf

MAX_GAP_DAYS = 14


@dataclass
class Pair:
    incoming: dict[str, Any]
    reply: dict[str, Any]


@dataclass
class ReplayScore:
    model: str
    incoming_id: str
    reply_id: str
    date: str
    contact: str
    language: str  # of your real reply
    reply_language: str = ""  # of Envoy's reply
    language_ok: bool = False
    numbers_ref: int = 0  # numbers in your real reply
    numbers_hit: int = 0  # of those, present in Envoy's reply
    numbers_extra: int = 0  # numbers Envoy stated that you did not
    chrf: float = 0.0
    status: str = ""
    sources_used: int = 0
    error: str = ""
    seconds: float = 0.0
    incoming_text: str = ""
    real_reply: str = ""
    envoy_reply: str = ""


def find_pairs(con, n: int = 30, contact: str = "", since: str = "") -> list[Pair]:
    """Incoming messages followed by your reply in the same thread (or to the
    same address within two weeks when threads are missing), newest first."""
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM messages WHERE excluded=0 AND text<>'' ORDER BY date")]
    mine = [r for r in rows if r["is_mine"]]
    theirs = [r for r in rows if not r["is_mine"]]
    pairs: list[Pair] = []
    used: set[str] = set()
    for inc in theirs:
        if contact and inc["from_addr"] != contact.lower():
            continue
        if since and inc["date"] < since:
            continue
        candidates = [m for m in mine if m["id"] not in used and m["date"] > inc["date"]
                      and ((inc["thread_id"] and m["thread_id"] == inc["thread_id"])
                           or inc["from_addr"] in (m["to_addrs"] or ""))]
        candidates = [m for m in candidates
                      if _days_between(inc["date"], m["date"]) <= MAX_GAP_DAYS]
        if not candidates:
            continue
        reply = min(candidates, key=lambda m: m["date"])
        used.add(reply["id"])
        pairs.append(Pair(inc, reply))
    pairs.sort(key=lambda p: p.incoming["date"], reverse=True)
    return pairs[:n]


def _days_between(a: str, b: str) -> float:
    from datetime import datetime

    try:
        da = datetime.fromisoformat(a.replace("Z", "+00:00"))
        dbb = datetime.fromisoformat(b.replace("Z", "+00:00"))
        return abs((dbb - da).total_seconds()) / 86400
    except ValueError:
        return 0.0


def score_pair(pair: Pair, envoy_text: str) -> dict[str, Any]:
    ref, hyp = pair.reply["text"], envoy_text
    ref_nums, hyp_nums = numbers(ref), numbers(hyp)
    lang_ref = pair.reply["language"] or detect_language(ref)
    lang_hyp = detect_language(hyp)
    return {"language": lang_ref, "reply_language": lang_hyp,
            "language_ok": lang_hyp == lang_ref,
            "numbers_ref": len(ref_nums), "numbers_hit": len(ref_nums & hyp_nums),
            "numbers_extra": len(hyp_nums - ref_nums), "chrf": round(chrf(hyp, ref), 1)}


async def run_replay(settings: Settings, con=None, models: list[str] | None = None,
                     n: int = 30, contact: str = "", since: str = "", on_row=None
                     ) -> list[ReplayScore]:
    con = con if con is not None else db.connect(settings.db_path)
    pairs = find_pairs(con, n, contact, since)
    base = build_model(settings)
    names = models or [getattr(base, "model", base.name)]
    embedder = build_embedder(settings)
    rows: list[ReplayScore] = []
    for name in names:
        model = base.with_model(name) if hasattr(base, "with_model") and name != getattr(
            base, "model", None) else base
        for pair in pairs:
            inc, rep = pair.incoming, pair.reply
            t0 = time.perf_counter()
            row = ReplayScore(model=model.name, incoming_id=inc["id"], reply_id=rep["id"],
                              date=inc["date"], contact=inc["from_addr"],
                              language=rep["language"] or detect_language(rep["text"]),
                              incoming_text=inc["text"], real_reply=rep["text"])
            contact_row = db.contact_by_email(con, inc["from_addr"])
            tools = DirectTools(con, embedder, before=inc["date"])
            try:
                r = await compose(ComposeRequest(message=inc["text"],
                                                 contact_id=contact_row["id"] if contact_row
                                                 else None),
                                  settings=settings, model=model, tools=tools, con=con)
                db.history_delete(con, r.id)  # a replay is not a real reply
                row.envoy_reply, row.status = r.final_text, r.status.value
                row.sources_used = len({sid for e in r.ledger for sid in e.source_ids})
                for k, v in score_pair(pair, r.final_text).items():
                    setattr(row, k, v)
            except PipelineError as e:
                row.error = str(e)[:300]
            row.seconds = round(time.perf_counter() - t0, 1)
            rows.append(row)
            if on_row:
                on_row(row)
    return rows


def summarize(rows: list[ReplayScore | dict[str, Any]]) -> dict[str, Any]:
    rs = [r if isinstance(r, dict) else asdict(r) for r in rows]
    ok = [r for r in rs if not r["error"]]
    with_nums = [r for r in ok if r["numbers_ref"]]
    return {
        "n": len(rs), "errors": len(rs) - len(ok),
        "language_ok": sum(1 for r in ok if r["language_ok"]),
        "pairs_with_numbers": len(with_nums),
        "numbers_ref": sum(r["numbers_ref"] for r in with_nums),
        "numbers_hit": sum(r["numbers_hit"] for r in with_nums),
        "numbers_extra": sum(r["numbers_extra"] for r in ok),
        "chrf_mean": round(sum(r["chrf"] for r in ok) / len(ok), 1) if ok else 0.0,
        "ready": sum(1 for r in ok if r["status"] == "ready"),
        "check": sum(1 for r in ok if r["status"] == "check"),
        "escalate": sum(1 for r in ok if r["status"] == "escalate"),
        "with_sources": sum(1 for r in ok if r["sources_used"]),
    }


def render_replay(rows: list[ReplayScore]) -> str:
    lines = []
    by_model: dict[str, list[ReplayScore]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    for model, rs in by_model.items():
        s = summarize(rs)
        lines.append(f"\nReplay of your inbox, {model}: {s['n']} exchanges, {s['errors']} errors")
        lines.append(f"  {'date':10} {'contact':26} {'lang':4} {'ok':3} {'nums':7} {'extra':5} "
                     f"{'chrF':5} {'status':9} {'src':>3} {'s':>5}")
        for r in rs:
            lines.append(f"  {r.date[:10]:10} {r.contact[:26]:26} {r.language:4} "
                         f"{'yes' if r.language_ok else 'NO':3} "
                         f"{r.numbers_hit}/{r.numbers_ref:<5} {r.numbers_extra:5} "
                         f"{r.chrf:5.1f} {r.status or 'ERROR':9} {r.sources_used:>3} "
                         f"{r.seconds:>5}" + (f"  {r.error}" if r.error else ""))
        lines.append(f"  language matched {s['language_ok']}/{s['n'] - s['errors']}; numbers from "
                     f"your real replies also in Envoy's: {s['numbers_hit']}/{s['numbers_ref']} "
                     f"over {s['pairs_with_numbers']} exchanges; extra numbers "
                     f"{s['numbers_extra']}; mean chrF {s['chrf_mean']}; ready {s['ready']}, "
                     f"check {s['check']}, escalate {s['escalate']}; used sources in "
                     f"{s['with_sources']}")
    return "\n".join(lines)


def replay_to_dicts(rows: list[ReplayScore]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rows]
