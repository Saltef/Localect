"""A deterministic stand-in for a language model.

It is not a model. It exists so the whole product runs offline, in CI, and in
environments where weights cannot be downloaded, and so tests are exactly
reproducible. Its outputs are plausible, schema-valid, and honest about what
they are: greetings and sign-offs come from the locale profile, answers quote
the user's own knowledge, and it never invents a fact.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from ..text import fill_name as _fill_name
from ..text import keywords, score, to_eastern, to_western
from ..text import tokens as _tokens
from .base import Message

_ARABIC = re.compile(r"[؀-ۿ]")
_JAPANESE = re.compile(r"[぀-ヿ一-龯]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")

_LANG_WORDS = {
    "es": {"gracias", "usted", "hola", "cuándo", "dónde", "envío", "reembolso", "quisiera",
           "necesito", "pedido", "buenos", "días", "saludos", "también", "cuál", "cuánto",
           "qué", "es", "cubre", "después", "todavía", "cierre", "tiene", "tienen"},
    "pt": {"obrigado", "obrigada", "você", "não", "olá", "quando", "onde", "envio",
           "reembolso", "gostaria", "preciso", "pedido", "bom", "dia", "também", "qual",
           "é", "isso", "depois", "coberto", "coberta", "ainda", "boa", "tarde", "têm",
           "encomenda", "oi", "quanto", "quantos", "uma", "eu", "meu", "minha", "até",
           "pra"},
    "fr": {"bonjour", "merci", "commande", "vous", "je", "pour", "remboursement",
           "livraison", "quand", "où", "pourriez", "cordialement", "combien", "quel", "quelle",
           "est", "le", "la", "les", "une", "des", "temps", "aujourd'hui", "toujours", "ma",
           "mon", "prend"},
    "de": {"hallo", "danke", "bestellung", "ich", "bitte", "und", "nicht",
           "rückerstattung", "lieferung", "wann", "können", "grüße", "guten", "wie", "lange",
           "dauert", "eine", "der", "die", "das", "bis", "nach", "sie", "haben"},
    "en": {"the", "please", "order", "refund", "shipping", "when", "thanks", "hello",
           "could", "would", "you", "my"},
}

_REGION_WORDS = {
    "ar": [("ar-EG", {"ازيك", "إزيك", "عايز", "عايزة", "ايه", "إيه", "كده", "دلوقتي", "ازاي",
                      "إزاي", "بتاع", "بتاعت", "كام", "لسه", "فين", "فندم"}),
           ("ar-SA", {"شلونك", "شلونكم", "وش", "ابي", "أبي", "ابغى", "أبغى", "الحين", "زين",
                      "حياك", "حياكم"}),
           ("ar-LB", {"كيفك", "كيفكن", "شو", "بدي", "هلق", "هلأ", "منيح", "ليش", "عندكن",
                      "قديش", "لسا", "هيك"})],
    "pt": [("pt-PT", {"vós", "vosso", "vossa", "telemóvel", "autocarro", "pequeno-almoço",
                      "estou a", "encomenda", "encomendei", "obrigado pela atenção",
                      "portátil", "mais pequeno", "mais pequena"}),
           ("pt-BR", {"você", "vocês", "celular", "ônibus", "legal"})],
    "es": [("es-ES", {"vosotros", "vale", "ordenador", "móvil", "coche", "portátil", "os",
                      "vuestro", "vuestra", "tenéis", "podéis", "enviáis", "sabéis"}),
           ("es-MX", {"ahorita", "platicar", "celular", "computadora", "órale", "mande"})],
    "en": [("en-GB", {"colour", "favour", "cheers", "whilst", "postcode", "fortnight",
                      "rucksack"}),
           ("en-US", {"color", "favor", "zip", "gotten"})],
}
_DEFAULT_REGION = {"ar": "ar-EG", "pt": "pt-BR", "es": "es-MX", "en": "en-US",
                   "fr": "fr-FR", "de": "de-DE", "ja": "ja-JP"}

_NUM = r"\d+(?:[.,]\d+)*"
_PRESERVE = re.compile(
    r"(?:#\d{3,}|[A-Z]{2,}-?\d{3,}|\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}"
    r"|[\w.+-]+@[\w-]+\.[\w.]+|" + _NUM + r"\s?(?:%|€|\$|£|EGP|SAR|USD|EUR|GBP|BRL|MXN|JPY)"
    r"|(?:€|\$|£)\s?" + _NUM + r"|[٠-٩]+|\b\d+\b)"
)


def detect_language(text: str) -> str:
    if _ARABIC.search(text):
        return "ar"
    if _JAPANESE.search(text):
        return "ja"
    if _CYRILLIC.search(text):
        return "ru"
    words = set(re.findall(r"[\wÀ-ÿ']+", text.lower()))
    best, score = "en", 0
    for lang, vocab in _LANG_WORDS.items():
        s = len(words & vocab)
        if s > score:
            best, score = lang, s
    return best


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w'-]+", text.lower()))


def guess_region(text: str, language: str) -> str | None:
    low = text.lower()
    words = _words(text)
    for locale, markers in _REGION_WORDS.get(language, []):
        for m in markers:
            if (" " in m and m in low) or (" " not in m and m in words):
                return locale
    return _DEFAULT_REGION.get(language)


def extract_preserve(text: str) -> list[str]:
    seen: list[str] = []
    for m in _PRESERVE.findall(text):
        m = m.strip()
        if m and m not in seen:
            seen.append(m)
    return seen




def _avoid_phrases(notes: str) -> list[str]:
    m = re.search(r"avoid:\s*(.+)$", notes, re.IGNORECASE)
    if not m:
        return []
    return [p.strip().lower() for p in m.group(1).split(";") if p.strip()]


class StubModel:
    name = "stub"

    def generate(
        self,
        messages: list[Message],
        *,
        role: str,
        schema: type[BaseModel] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        ctx = context or {}
        fn = getattr(self, f"_{role}", None)
        if fn is None:
            raise ValueError(f"stub has no behaviour for role {role!r}")
        return json.dumps(fn(ctx), ensure_ascii=False)

    # -- reader -----------------------------------------------------------
    def _reader(self, ctx: dict[str, Any]) -> dict[str, Any]:
        msg: str = ctx["message"]
        lang = detect_language(msg)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?؟。？！])\s*", msg) if s.strip()]
        # A question ends in a question mark, or, in Japanese, in か。
        asks = [s for s in sentences if (s.endswith(("?", "؟", "？")) or s.endswith("か。"))
                and (len(s.split()) > 2 or _JAPANESE.search(s))]
        return {
            "language": lang,
            "language_name": {"ar": "Arabic", "es": "Spanish", "pt": "Portuguese", "fr": "French",
                              "de": "German", "ja": "Japanese", "ru": "Russian", "en": "English"
                              }.get(lang, lang),
            "region_guess": guess_region(msg, lang),
            "gloss": f"[stub gloss, {lang}] {msg.strip()}"
                     + (f" | keywords: {' '.join(kw)}" if (kw := keywords(msg)) else ""),
            "intent": (sentences[0] if sentences else msg.strip())[:120],
            "asks": asks,
            "must_preserve": extract_preserve(msg),
            "tone": "neutral",
        }

    # -- extractor --------------------------------------------------------
    def _extractor(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Every sentence that fixes a number is a fact; its topic is the
        sentence's canonical (alias-folded) words, so the same statement in two
        languages gets the same key. Real models write a proper English topic."""
        from ..text import ALIASES

        facts = []
        text: str = ctx.get("text", "")
        for sent in re.split(r"(?<=[.!?؟。])\s+|\n+", text):
            sent = sent.strip()
            if not sent or not re.search(r"\d", to_western(sent)):
                continue
            nums = re.findall(r"\d+(?:[.,]\d+)?", to_western(sent))
            words = _tokens(sent) - {to_western(n) for n in nums}
            concepts = sorted(w for w in words if w in ALIASES)
            topic = " ".join(concepts or sorted(words))[:60] or "untitled"
            facts.append({"topic": topic, "statement": sent, "value": nums[0]})
        return {"facts": facts}

    # -- drafter ----------------------------------------------------------
    def _drafter(self, ctx: dict[str, Any]) -> dict[str, Any]:
        reading = ctx["reading"]
        locale = ctx["locale"]
        sources = ctx.get("sources", [])
        name = ctx.get("contact_name", "")
        user_name = ctx.get("user_name", "")
        # Facts come from the knowledge base, from the user's own past mail, and
        # from the dated facts extracted from it.
        knowledge = [s for s in sources if s["kind"] in ("knowledge", "mail", "fact")]
        segments = []
        greeting = _fill_name(locale["greeting"], name, locale["language"])
        segments.append({"id": "s1", "text": greeting, "claims": []})
        asks = reading.get("asks") or [reading.get("intent", "")]
        n = 2
        for ask in asks:
            terms = _tokens(ask)
            best, best_score = None, (0, 0)
            for k in knowledge:
                # The section title is a strong hint of topic ("Returns and refunds").
                # On a tie, the earlier paragraph of an entry wins: knowledge bases
                # state the general rule first and the special cases after it.
                meta = k.get("meta", {})
                title = str(meta.get("title", ""))
                s = (score(_tokens(k["text"]), terms) + score(_tokens(title), terms),
                     -int(meta.get("start", 0) or 0))
                if s[0] and s > best_score:
                    best, best_score = k, s
            if best:
                segments.append({"id": f"s{n}", "text": best["text"],
                                 "claims": [{"text": best["text"], "source_ids": [best["id"]]}]})
            else:
                segments.append({"id": f"s{n}",
                                 "text": "We will confirm this and get back to you shortly.",
                                 "claims": []})
            n += 1
        signoff = locale["signoff"] + (f"\n{user_name}" if user_name else "")
        segments.append({"id": f"s{n}", "text": signoff, "claims": []})
        return {"language": locale["language"], "segments": segments,
                "notes": "stub draft: greeting and sign-off from the locale profile; "
                         "answers quote the knowledge base verbatim"}

    # -- rewriter ---------------------------------------------------------
    def _rewriter(self, ctx: dict[str, Any]) -> dict[str, Any]:
        draft = ctx["draft"]
        locale = ctx["locale"]
        preserve = ctx.get("must_preserve", [])
        eastern = locale["formats"]["numerals"] == "eastern-arabic"
        segments, changes = [], []
        for seg in draft["segments"]:
            text = seg["text"]
            if "[[DRIFT]]" in text:
                # Test hook: a deliberately careless first rewrite that drops a fact,
                # which a revision pass (with the Critic's flag) then restores.
                text = text.replace("[[DRIFT]]", "").strip()
                if preserve and not ctx.get("revise"):
                    text = text.replace(preserve[0], "").strip()
                    changes.append({"segment_id": seg["id"], "kind": "idiom",
                                    "note": "smoothed phrasing"})
            if eastern:
                new = to_eastern(text)
                if new != text:
                    changes.append({"segment_id": seg["id"], "kind": "format",
                                    "note": "numerals rendered in Eastern Arabic digits"})
                text = new
            segments.append({"id": seg["id"], "text": text})
        if segments:
            changes.append({"segment_id": segments[0]["id"], "kind": "greeting",
                            "note": f"greeting follows {locale['variety']} convention"})
        return {"segments": segments, "changes": changes}

    # -- critic -----------------------------------------------------------
    def _critic(self, ctx: dict[str, Any]) -> dict[str, Any]:
        draft = {s["id"]: s for s in ctx["draft"]["segments"]}
        rewrite = ctx["rewrite"]["segments"]
        locale = ctx["locale"]
        preserve = [to_western(p) for p in ctx.get("must_preserve", [])]
        glossary = ctx.get("glossary", [])
        avoid = _avoid_phrases(locale.get("notes", ""))
        back, flags = [], []
        for seg in rewrite:
            final = seg["text"]
            final_w = to_western(final)
            back.append({"id": seg["id"], "text": final_w})
            d = draft.get(seg["id"])
            if d is None:
                continue
            draft_w = to_western(d["text"])
            for item in preserve:
                if item in draft_w and item not in final_w:
                    flags.append({"segment_id": seg["id"], "kind": "drifted", "span": item,
                                  "reason": f"'{item}' is in the draft but missing after rewrite",
                                  "severity": "block"})
            for g in glossary:
                term = g["term"]
                if term.lower() in draft_w.lower():
                    if g.get("do_not_translate") and term not in final:
                        flags.append({"segment_id": seg["id"], "kind": "off_glossary",
                                      "span": term, "reason": f"'{term}' must appear unchanged",
                                      "severity": "block"})
                    elif g.get("rendering") and g["rendering"] not in final and term not in final:
                        flags.append({"segment_id": seg["id"], "kind": "off_glossary",
                                      "span": term,
                                      "reason": f"'{term}' should be rendered as "
                                                f"'{g['rendering']}'",
                                      "severity": "block"})
            for c in d.get("claims", []):
                if not c.get("source_ids"):
                    flags.append({"segment_id": seg["id"], "kind": "unsupported_claim",
                                  "span": c["text"][:60],
                                  "reason": "claim has no source", "severity": "block"})
            low = final.lower()
            for phrase in avoid:
                if phrase and phrase in low:
                    flags.append({"segment_id": seg["id"], "kind": "cultural_risk",
                                  "span": phrase,
                                  "reason": f"locale profile says to avoid '{phrase}'",
                                  "severity": "warn"})
        return {"back_segments": back, "flags": flags}
