"""The Reader against MASSIVE (Amazon), 51 languages of intent and slot data.

Envoy's Reader must say what language a message is in and pull out what a
reply has to keep exactly: names, dates, times, amounts, addresses. MASSIVE
labels exactly those spans, in the languages Envoy ships, so it is a
ready-made test of the Reader with no prompt of ours in the loop.

Two numbers per language:

- language accuracy: the Reader's ISO code matches the utterance's locale.
- slot recall: of the labelled spans a reply would have to preserve (dates,
  times, people, email addresses, business and place names, currencies),
  the share the Reader put into ``must_preserve`` (strict) or anywhere in
  its reading (lenient: must_preserve, asks, gloss, intent).

Data: https://github.com/alexa/massive (version 1.1). Point ``--data`` at
the unpacked directory; files are found as ``data/<locale>.jsonl``.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..agents import reader
from ..agents.stage import StageError
from ..config import Settings
from ..models import build_model
from ..pipeline import LANG_NAMES
from ..text import has_value

MASSIVE_LOCALES = {"ar": "ar-SA", "pt": "pt-BR", "es": "es-ES", "fr": "fr-FR", "de": "de-DE",
                   "en": "en-US", "ja": "ja-JP"}
# Slot labels whose values a reply must keep exactly. Others (food_type,
# device_type, weather descriptors) are things a reply may rephrase.
PRESERVABLE = {"date", "time", "person", "email_address", "business_name", "place_name",
               "currency_name", "house_place", "event_name"}
_SLOT = re.compile(r"\[\s*([a-z_]+)\s*:\s*([^\]]+?)\s*\]")


@dataclass
class Utterance:
    id: str
    locale: str
    language: str
    text: str
    intent: str
    slots: list[tuple[str, str]]


def parse_slots(annot_utt: str) -> list[tuple[str, str]]:
    return [(label, value.strip()) for label, value in _SLOT.findall(annot_utt)]


def find_file(data_dir: Path, locale: str) -> Path | None:
    for candidate in (data_dir / "data" / f"{locale}.jsonl", data_dir / f"{locale}.jsonl"):
        if candidate.exists():
            return candidate
    found = sorted(data_dir.rglob(f"{locale}.jsonl"))
    return found[0] if found else None


def load_massive(data_dir: Path, languages: list[str] | None = None, n: int = 50,
                 partition: str = "test", seed: int = 7) -> list[Utterance]:
    """``n`` utterances per language from the given partition, sampled with a
    fixed seed so two runs compare the same sentences."""
    out: list[Utterance] = []
    for lang in languages or list(MASSIVE_LOCALES):
        locale = MASSIVE_LOCALES.get(lang, lang)
        f = find_file(data_dir, locale)
        if f is None:
            continue
        rows = []
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if partition and r.get("partition") != partition:
                    continue
                rows.append(Utterance(id=str(r.get("id", "")), locale=r.get("locale", locale),
                                      language=lang, text=r.get("utt", ""),
                                      intent=r.get("intent", ""),
                                      slots=parse_slots(r.get("annot_utt", ""))))
        random.Random(seed).shuffle(rows)
        out += rows[:n]
    return out


@dataclass
class ReaderScore:
    model: str
    id: str
    language: str
    locale: str
    text: str
    seconds: float = 0.0
    detected: str = ""
    language_ok: bool = False
    slots: int = 0
    slots_strict: int = 0
    slots_lenient: int = 0
    missed: list[str] = field(default_factory=list)
    error: str = ""


def score_reading(reading, utt: Utterance) -> ReaderScore:
    row = ReaderScore(model="", id=utt.id, language=utt.language, locale=utt.locale,
                      text=utt.text, detected=reading.language,
                      language_ok=reading.language == utt.language)
    strict = " ".join(reading.must_preserve)
    lenient = " ".join([strict, *reading.asks, reading.gloss, reading.intent])
    for label, value in utt.slots:
        if label not in PRESERVABLE:
            continue
        row.slots += 1
        if has_value(strict, value):
            row.slots_strict += 1
        if has_value(lenient, value):
            row.slots_lenient += 1
        else:
            row.missed.append(f"{label}={value}")
    return row


async def run_massive(settings: Settings, data_dir: Path, languages: list[str] | None = None,
                      n: int = 50, models: list[str] | None = None, on_row=None
                      ) -> list[ReaderScore]:
    utts = load_massive(data_dir, languages, n)
    base = build_model(settings)
    names = models or [getattr(base, "model", base.name)]
    user_language_name = LANG_NAMES.get(settings.user_language, settings.user_language)
    rows: list[ReaderScore] = []
    for name in names:
        model = base.with_model(name) if hasattr(base, "with_model") and name != getattr(
            base, "model", None) else base
        for u in utts:
            t0 = time.perf_counter()
            try:
                reading = await reader.read(model, u.text, user_language_name)
                row = score_reading(reading, u)
            except StageError as e:
                row = ReaderScore(model="", id=u.id, language=u.language, locale=u.locale,
                                  text=u.text, error=str(e)[:200])
            row.model = model.name
            row.seconds = round(time.perf_counter() - t0, 1)
            rows.append(row)
            if on_row:
                on_row(row)
    return rows


def render_massive(rows: list[ReaderScore]) -> str:
    lines = []
    by_model: dict[str, list[ReaderScore]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    for model, rs in by_model.items():
        lines.append(f"\nReader on MASSIVE, {model}: {len(rs)} utterances, "
                     f"{sum(r.seconds for r in rs):.0f}s")
        lines.append(f"  {'lang':5} {'n':>4} {'errors':>6} {'language':>9} {'slots':>6} "
                     f"{'strict':>7} {'lenient':>8}")
        by_lang: dict[str, list[ReaderScore]] = {}
        for r in rs:
            by_lang.setdefault(r.language, []).append(r)
        for lang, ls in sorted(by_lang.items()):
            ok = [r for r in ls if not r.error]
            n = len(ok)
            slots = sum(r.slots for r in ok)
            acc = f"{100 * sum(r.language_ok for r in ok) / n:4.0f}%" if n else "   -"
            strict = f"{100 * sum(r.slots_strict for r in ok) / slots:4.0f}%" if slots else "   -"
            lenient = f"{100 * sum(r.slots_lenient for r in ok) / slots:4.0f}%" if slots \
                else "   -"
            lines.append(f"  {lang:5} {len(ls):>4} {len(ls) - n:>6} {acc:>9} {slots:>6} "
                         f"{strict:>7} {lenient:>8}")
    return "\n".join(lines)


def massive_to_dicts(rows: list[ReaderScore]) -> list[dict]:
    return [asdict(r) for r in rows]
