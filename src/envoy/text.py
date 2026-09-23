"""Shared text utilities: a canonical tokenizer with a small cross-lingual
alias table for commerce vocabulary, and numeral conversion.

The alias table lets lexical retrieval match a question asked in one language
against knowledge written in another without any model. It is deliberately
small and domain-specific; it is a floor, not the ceiling.
"""

from __future__ import annotations

import re

_EASTERN = "٠١٢٣٤٥٦٧٨٩"
_WESTERN = "0123456789"

ALIASES: dict[str, set[str]] = {
    "order": {"orders", "pedido", "pedidos", "commande", "bestellung", "طلب", "طلبي", "طلبية",
              "注文", "encomenda"},
    "shipping": {"ship", "ships", "shipped", "delivery", "deliver", "delivered", "arrive",
                 "arrives", "envío", "envio", "entrega", "expédition", "livraison", "versand",
                 "lieferung", "شحن", "الشحن", "توصيل", "يوصل", "بيوصل", "وصول", "配送", "配達",
                 "llega", "chega", "ankommt"},
    "tracking": {"track", "seguimiento", "rastreio", "rastreamento", "suivi",
                 "sendungsverfolgung", "تتبع", "追跡"},
    "return": {"returns", "devolución", "devolucion", "devolução", "devolucao", "retour",
               "rückgabe", "rueckgabe", "إرجاع", "ارجاع", "الإرجاع", "الارجاع", "ترجيع", "返品"},
    "refund": {"refunds", "reembolso", "remboursement", "rückerstattung", "rueckerstattung",
               "استرداد", "الاسترداد", "返金"},
    "policy": {"política", "politica", "politique", "richtlinie", "سياسة", "ポリシー"},
    "days": {"day", "días", "dias", "jours", "tage", "أيام", "ايام", "يوم", "日"},
    "when": {"cuándo", "cuando", "quando", "quand", "wann", "متى", "إمتى", "امتى", "いつ"},
    "price": {"prices", "precio", "preço", "preco", "prix", "preis", "سعر", "السعر", "価格"},
    "size": {"sizes", "talla", "tamanho", "taille", "größe", "groesse", "مقاس", "المقاس",
             "サイズ"},
    "warranty": {"garantía", "garantia", "garantie", "ضمان", "الضمان", "保証"},
    "hours": {"horario", "horário", "horaires", "öffnungszeiten", "ساعات", "営業時間"},
    "cancel": {"cancelar", "annuler", "stornieren", "إلغاء", "الغاء", "キャンセル"},
    "discount": {"descuento", "desconto", "remise", "rabatt", "خصم", "割引"},
    "invoice": {"factura", "fatura", "facture", "rechnung", "فاتورة", "請求書"},
}
_INDEX: dict[str, str] = {}
for _head, _alts in ALIASES.items():
    _INDEX[_head] = _head
    for _a in _alts:
        _INDEX[_a] = _head

_AR_PREFIXES = ("وال", "بال", "لل", "ال", "و", "ب", "ل", "ف")


def canon(token: str) -> str:
    if token in _INDEX:
        return _INDEX[token]
    if token.endswith("s") and token[:-1] in _INDEX:
        return _INDEX[token[:-1]]
    for pre in _AR_PREFIXES:
        rest = token[len(pre):]
        if token.startswith(pre) and rest in _INDEX:
            return _INDEX[rest]
    return token


STOPWORDS = {
    # en
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had", "has", "have",
    "her", "his", "its", "our", "out", "she", "was", "who", "will", "with", "what", "when",
    "this", "that", "from", "they", "been", "were", "your", "does", "did", "how", "why", "hi",
    "hello", "thanks", "please", "would", "could", "about", "there", "here", "into", "than",
    # es / pt
    "los", "las", "una", "uno", "del", "por", "para", "con", "que", "qué", "como", "cómo",
    "mi", "mis", "su", "sus", "es", "está", "hay", "hola", "gracias", "dos", "muy",
    "uma", "das", "não", "nao", "com", "meu", "minha", "olá", "obrigado", "obrigada",
    "ele", "ela", "isso", "esse", "essa", "tem", "ser", "foi", "mas", "também",
    # fr / de
    "les", "des", "une", "est", "pour", "avec", "vous", "nous", "votre", "notre", "merci",
    "bonjour", "sur", "dans", "pas", "qui", "quoi", "il", "elle", "ils",
    "der", "die", "und", "ist", "ich", "sie", "wir", "ihr", "mit", "für", "auf",
    "nicht", "ein", "eine", "einen", "hallo", "danke", "bitte", "zu", "von", "wie",
    # ar (function words, spelled out)
    "في", "من", "على", "إلى", "الى", "عن", "أن", "ان", "هذا", "هذه", "ذلك", "مع", "هل",
    "لا", "ما", "أنا", "انا", "أنت", "انت", "هو", "هي", "كان", "لكن", "أو", "او", "ثم",
    "مرحبا", "مرحباً", "شكرا", "شكراً", "كيفك", "ازيك", "شلونك", "بدي", "عايز", "أبغى",
    "ابغى", "بيوصل", "رقم", "شو", "ايه", "إيه", "وش", "ليش", "متى", "امتى", "إمتى",
}


def tokens(text: str) -> set[str]:
    out = set()
    for raw in re.findall(r"\w+", text.lower()):
        c = canon(raw)
        if c in ALIASES:
            out.add(c)
        elif len(raw) > 2 and raw not in STOPWORDS:
            out.add(raw)
    return out


def score(a: set[str], b: set[str]) -> int:
    """Overlap weighted toward domain terms."""
    return sum(3 if t in ALIASES else 1 for t in a & b)


def keywords(text: str) -> list[str]:
    """Alias heads found in the text, in order of first appearance."""
    out: list[str] = []
    for tok in re.findall(r"\w+", text.lower()):
        c = canon(tok)
        if c in ALIASES and c not in out:
            out.append(c)
    return out


def to_eastern(text: str) -> str:
    return text.translate(str.maketrans(_WESTERN, _EASTERN))


def to_western(text: str) -> str:
    return text.translate(str.maketrans(_EASTERN, _WESTERN))


_CITATION = re.compile(r"\s*\[?\b(?:kb|gl|hx|th):[A-Za-z0-9_:\-]+\]?")


def strip_citations(text: str) -> str:
    """Remove source ids a model may have written into prose ([kb:abc:0], gl:1)."""
    out = _CITATION.sub("", text)
    out = re.sub(r"[ \t]+([.,،؛:!?؟])", r"\1", out)  # no space before punctuation
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def fill_name(template: str, name: str, language: str) -> str:
    """Render a greeting/sign-off template; drop the name slot cleanly when unknown."""
    fallback = {"en": "there", "ja": "お客"}.get(language, "")
    who = name or fallback
    if not who:
        template = template.replace(", {name}", "").replace(" {name}", "").replace("{name}", "")
    out = template.replace("{name}", who)
    out = re.sub(r"[ \t]+", " ", out)
    for a, b in ((" ،", "،"), (" ,", ","), (" :", ":"), (" !", "!")):
        out = out.replace(a, b)
    return out.strip()
