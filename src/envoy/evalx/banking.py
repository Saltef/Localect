"""Real banking customers, in the languages Envoy ships, against the bank
knowledge base: Banking77 and its hand-localized Arabic and French versions.

Banking77 (PolyAI, CC BY 4.0) is 13,083 real customer queries to a banking
assistant, each labelled with one of 77 intents. ArBanking77 (Birzeit
University, CC BY-SA 4.0) localizes every query into Modern Standard Arabic
and Palestinian Arabic, and the test split also into Saudi, Moroccan and
Tunisian. WolBanking77 (CLAD Dakar, CC BY 4.0) translates 9,791 of them into
French. None of the queries were written for Envoy, and the labels give
each one a checkable expectation without a person reading the reply.

The bench composes a reply to each query against the Harbor Bank knowledge
base from the domains set. The 77 intents are mapped once, by hand, to what
that knowledge base says:

- a *covered* intent ("card arrival") has a number the reply must state
  (the replacement card takes 5 business days);
- an *uncovered* intent ("exchange rate") has no answer in the knowledge
  base, so the reply must state no number the customer did not give and no
  number the knowledge base does not hold: a policy invented for the
  occasion is the failure this bench exists to count.

Every reply is also checked for language (the Reader's language and the
reply's own), and the Arabic varieties for the region the Reader guessed:
a Saudi query should resolve to ar-SA, a Palestinian one to ar-LB, which is
Envoy's Levantine profile. Where a dialect scorer is installed (CAMeL
Tools), the draft-versus-final ablation runs on the Arabic replies too.

Data layout under ``--data``::

    banking77/test.csv                       text,category (PolyAI raw)
    arbanking77/Banking77_full_corpus.csv    the ArBanking77 corpus
    wolbanking77/*.csv                       any CSV with a French text column
                                             and a Banking77 intent column

Each file is optional; the bench runs on whatever is present.
"""

from __future__ import annotations

import csv
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .. import db
from ..config import Settings, data_dir
from ..eval import dialect_ablation
from ..evalset import domains
from ..locales import seed_locales
from ..models import build_model
from ..models.stub import detect_language
from ..pipeline import PipelineError, compose
from ..schemas import ComposeRequest
from ..text import has_value, numbers
from ..tools import DirectTools
from .dialect import discover

# Intent -> facts the reply must state, as lists of alternatives, from the
# Harbor Bank knowledge base in evalset/domains.yaml. Every other intent is
# uncovered: the bank says nothing about it, so the reply may not either.
INTENT_FACTS: dict[str, list[list[str]]] = {
    "card_arrival": [["5"]],
    "card_delivery_estimate": [["5"]],
    "lost_or_stolen_card": [["5"]],
    "compromised_card": [["5"]],
    "transfer_timing": [["15", "2", "4"]],
    "transfer_fee_charged": [["25"]],
    "extra_charge_on_statement": [["60", "10"]],
    "transaction_charged_twice": [["60", "10"]],
    "card_payment_not_recognised": [["60", "10"]],
    "direct_debit_payment_not_recognised": [["60", "10"]],
    "cash_withdrawal_not_recognised": [["60", "10"]],
}

# Which variety a column of the ArBanking77 corpus holds, and the region
# Envoy should resolve it to when it has a profile for that region.
ARABIC_COLUMNS = [
    ("Question_MSA1", "ar-MSA", None),
    ("Question_PAL1", "ar-PAL", "ar-LB"),
    ("Question_Saudi1", "ar-Saudi", "ar-SA"),
    ("Question_Moroccan", "ar-Moroccan", None),
    ("Question_Tunisian", "ar-Tunisian", None),
]
VARIETY_ORDER = ["en", "fr", "ar-MSA", "ar-PAL", "ar-Saudi", "ar-Moroccan", "ar-Tunisian"]


@dataclass
class Query:
    id: str
    variety: str
    language: str
    text: str
    intent: str
    region: str | None = None  # the locale a correct Reader resolves to, when known

    @property
    def covered(self) -> bool:
        return self.intent in INTENT_FACTS


@dataclass
class BankScore:
    model: str
    id: str
    variety: str
    language: str
    intent: str
    covered: bool
    text: str
    locale: str = ""
    status: str = ""
    language_ok: bool = False  # the Reader resolved the query's language
    reply_language: str = ""  # what the reply itself reads as
    reply_language_ok: bool = False
    region_ok: bool | None = None  # only for varieties Envoy has a profile for
    fact_ok: bool | None = None  # only for covered intents
    invented: list[str] = field(default_factory=list)  # numbers from nowhere
    flags_block: int = 0
    reply: str = ""
    dialect: dict[str, Any] | None = None
    seconds: float = 0.0
    error: str = ""

    @property
    def grounded(self) -> bool:
        return not self.error and not self.invented


def normalize_intent(label: str) -> str:
    return label.strip().lower().replace(" ", "_").rstrip("?")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        return list(csv.DictReader(fh, delimiter=delimiter))


def _pick(rows: list, n: int, seed: int) -> list:
    rows = list(rows)
    random.Random(seed).shuffle(rows)
    return rows[:n]


def load_banking(data_dir: Path, n: int = 10, seed: int = 7,
                 varieties: list[str] | None = None) -> list[Query]:
    """``n`` queries per variety, sampled with a fixed seed, so that two runs
    compare the same customers."""
    wanted = set(varieties or VARIETY_ORDER)
    out: list[Query] = []
    en = data_dir / "banking77" / "test.csv"
    if "en" in wanted and en.exists():
        rows = [r for r in _read_csv(en) if r.get("text") and r.get("category")]
        for i, r in enumerate(_pick(rows, n, seed)):
            out.append(Query(id=f"en-{i:03d}", variety="en", language="en", text=r["text"],
                             intent=normalize_intent(r["category"])))
    ar = data_dir / "arbanking77" / "Banking77_full_corpus.csv"
    if ar.exists():
        rows = _read_csv(ar)
        for column, variety, region in ARABIC_COLUMNS:
            if variety not in wanted:
                continue
            have = [r for r in rows if (r.get(column) or "").strip() and r.get("Intent_en")]
            for i, r in enumerate(_pick(have, n, seed)):
                out.append(Query(id=f"{variety}-{i:03d}", variety=variety, language="ar",
                                 text=r[column].strip(), intent=normalize_intent(r["Intent_en"]),
                                 region=region))
    fr_dir = data_dir / "wolbanking77"
    if "fr" in wanted and fr_dir.is_dir():
        rows = []
        for f in sorted(fr_dir.glob("*.csv")):
            for r in _read_csv(f):
                text_col = next((k for k in r if k and k.lower() in
                                 ("text_fr", "french", "fr", "text")), None)
                intent_col = next((k for k in r if k and k.lower() in
                                   ("intent", "category", "label", "intent_en")), None)
                if text_col and intent_col and r[text_col] and r[intent_col]:
                    intent = normalize_intent(r[intent_col])
                    if intent in KNOWN_INTENTS:
                        rows.append((r[text_col].strip(), intent))
        for i, (text, intent) in enumerate(_pick(rows, n, seed)):
            out.append(Query(id=f"fr-{i:03d}", variety="fr", language="fr", text=text,
                             intent=intent))
    return out


KNOWN_INTENTS = {
    "card_arrival", "card_linking", "exchange_rate", "card_payment_wrong_exchange_rate",
    "extra_charge_on_statement", "pending_cash_withdrawal", "fiat_currency_support",
    "card_delivery_estimate", "automatic_top_up", "card_not_working", "exchange_via_app",
    "lost_or_stolen_card", "age_limit", "pin_blocked", "contactless_not_working",
    "top_up_by_bank_transfer_charge", "pending_top_up", "cancel_transfer", "top_up_limits",
    "wrong_amount_of_cash_received", "card_payment_fee_charged",
    "transfer_not_received_by_recipient", "supported_cards_and_currencies",
    "getting_virtual_card", "card_acceptance", "top_up_reverted",
    "balance_not_updated_after_cheque_or_cash_deposit", "card_payment_not_recognised",
    "edit_personal_details", "why_verify_identity", "unable_to_verify_identity",
    "get_physical_card", "visa_or_mastercard", "topping_up_by_card", "disposable_card_limits",
    "compromised_card", "atm_support", "direct_debit_payment_not_recognised",
    "passcode_forgotten", "declined_cash_withdrawal", "pending_card_payment",
    "lost_or_stolen_phone", "request_refund", "declined_transfer", "refund_not_showing_up",
    "declined_card_payment", "pending_transfer", "terminate_account", "card_swallowed",
    "transaction_charged_twice", "verify_source_of_funds", "transfer_timing",
    "reverted_card_payment", "change_pin", "beneficiary_not_allowed", "transfer_fee_charged",
    "receiving_money", "failed_transfer", "transfer_into_account", "verify_top_up",
    "getting_spare_card", "top_up_by_cash_or_cheque", "order_physical_card",
    "virtual_card_not_working", "wrong_exchange_rate_for_cash_withdrawal",
    "get_disposable_virtual_card", "top_up_failed", "balance_not_updated_after_bank_transfer",
    "cash_withdrawal_not_recognised", "exchange_charge", "top_up_by_card_charge",
    "activate_my_card", "cash_withdrawal_charge", "card_about_to_expire",
    "apple_pay_or_google_pay", "verify_my_identity", "country_support",
}


def bank_store():
    """A fresh store holding only the Harbor Bank knowledge base. Returns the
    connection and the set of numbers the knowledge base states."""
    con = db.connect()
    seed_locales(con)
    dom = domains()["bank"]
    dom.seed(con)
    known = set()
    for _title, text in dom.knowledge:
        known |= numbers(text)
    return con, known


def score_query(q: Query, result, known: set[str], scorer=None) -> BankScore:
    reply = result.final_text
    row = BankScore(model="", id=q.id, variety=q.variety, language=q.language, intent=q.intent,
                    covered=q.covered, text=q.text, locale=result.locale.locale,
                    status=result.status.value, reply=reply)
    row.language_ok = result.locale.language == q.language
    row.reply_language = detect_language(reply)
    row.reply_language_ok = row.reply_language == q.language
    if q.region:
        row.region_ok = result.locale.locale == q.region
    if q.covered:
        row.fact_ok = all(any(has_value(reply, alt) for alt in alts)
                          for alts in INTENT_FACTS[q.intent])
    row.invented = sorted(numbers(reply) - numbers(q.text) - known, key=lambda x: (len(x), x))
    row.flags_block = sum(1 for f in result.flags if f.severity == "block")
    if scorer is not None and q.language == "ar":
        row.dialect = dialect_ablation(result, scorer)
    return row


async def run_banking(settings: Settings, data: Path, n: int = 10, models: list[str] | None = None,
                      on_row=None, seed: int = 7, varieties: list[str] | None = None,
                      scorers: dict | None = None) -> list[BankScore]:
    queries = load_banking(data, n, seed, varieties)
    if not queries:
        return []
    base = build_model(settings)
    names = models or [getattr(base, "model", base.name)]
    scorers = discover(data_dir()) if scorers is None else scorers
    con, known = bank_store()
    rows: list[BankScore] = []
    for name in names:
        model = base.with_model(name) if hasattr(base, "with_model") and name != getattr(
            base, "model", None) else base
        for q in queries:
            t0 = time.perf_counter()
            try:
                r = await compose(ComposeRequest(message=q.text), settings=settings,
                                  model=model, tools=DirectTools(con), con=con)
                db.history_delete(con, r.id)
                row = score_query(q, r, known, scorers.get("ar"))
            except PipelineError as e:
                row = BankScore(model="", id=q.id, variety=q.variety, language=q.language,
                                intent=q.intent, covered=q.covered, text=q.text,
                                error=str(e)[:300])
            row.model = model.name
            row.seconds = round(time.perf_counter() - t0, 1)
            rows.append(row)
            if on_row:
                on_row(row)
    return rows


def summarize(rows: list[BankScore | dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per variety: counts a reader can check, never a bare percentage."""
    rs = [r if isinstance(r, dict) else asdict(r) for r in rows]
    out: dict[str, dict[str, Any]] = {}
    for v in VARIETY_ORDER:
        vs = [r for r in rs if r["variety"] == v]
        if not vs:
            continue
        ok = [r for r in vs if not r["error"]]
        covered = [r for r in ok if r["covered"]]
        regioned = [r for r in ok if r["region_ok"] is not None]
        dialect = [r for r in ok if r.get("dialect")]
        out[v] = {
            "n": len(vs), "errors": len(vs) - len(ok),
            "language": (sum(r["language_ok"] for r in ok), len(ok)),
            "reply_language": (sum(r["reply_language_ok"] for r in ok), len(ok)),
            "region": (sum(bool(r["region_ok"]) for r in regioned), len(regioned)),
            "fact": (sum(bool(r["fact_ok"]) for r in covered), len(covered)),
            "grounded": (sum(not r["invented"] for r in ok), len(ok)),
            "escalate": (sum(r["status"] == "escalate" for r in ok), len(ok)),
            "dialect_draft": (sum(bool(r["dialect"]["draft_ok"]) for r in dialect), len(dialect)),
            "dialect_final": (sum(bool(r["dialect"]["final_ok"]) for r in dialect), len(dialect)),
            "locales": _top(r["locale"] for r in ok),
        }
    return out


def _top(values, k: int = 3) -> str:
    counts: dict[str, int] = {}
    for v in values:
        counts[v or "?"] = counts.get(v or "?", 0) + 1
    return ", ".join(f"{loc} {n}" for loc, n in
                     sorted(counts.items(), key=lambda kv: -kv[1])[:k])


def _frac(pair: tuple[int, int]) -> str:
    k, n = pair
    return f"{k}/{n}" if n else "-"


def render_banking(rows: list[BankScore]) -> str:
    by_model: dict[str, list[BankScore]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    lines = []
    for model, rs in by_model.items():
        s = summarize(rs)
        lines.append(f"\nBanking customers (Banking77, ArBanking77, WolBanking77) on {model}: "
                     f"{len(rs)} queries")
        lines.append(f"  {'variety':12} {'n':>3} {'lang':>6} {'reply':>6} {'region':>7} "
                     f"{'fact':>6} {'grounded':>9} {'escal.':>7}  resolved to")
        for v, d in s.items():
            lines.append(f"  {v:12} {d['n']:>3} {_frac(d['language']):>6} "
                         f"{_frac(d['reply_language']):>6} {_frac(d['region']):>7} "
                         f"{_frac(d['fact']):>6} {_frac(d['grounded']):>9} "
                         f"{_frac(d['escalate']):>7}  {d['locales']}")
        if any(d["dialect_final"][1] for d in s.values()):
            lines.append("  dialect (CAMeL), draft -> final: " + "; ".join(
                f"{v} {_frac(d['dialect_draft'])} -> {_frac(d['dialect_final'])}"
                for v, d in s.items() if d["dialect_final"][1]))
        invented = [r for r in rs if r.invented]
        if invented:
            lines.append(f"  invented numbers in {len(invented)} replies, e.g. "
                         + "; ".join(f"{r.id} [{r.intent}]: {', '.join(r.invented[:3])}"
                                     for r in invented[:5]))
        lines.append("  lang = the Reader resolved the query's language; reply = the reply "
                     "reads as that language; region = Saudi -> ar-SA, Palestinian -> ar-LB; "
                     "fact = covered intents state the bank's number; grounded = no number "
                     "from outside the query and the knowledge base")
    return "\n".join(lines)


def banking_to_dicts(rows: list[BankScore]) -> list[dict[str, Any]]:
    return [{**asdict(r), "grounded": r.grounded} for r in rows]
