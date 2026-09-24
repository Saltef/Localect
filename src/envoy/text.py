"""Shared text utilities: a canonical tokenizer with a small cross-lingual
alias table for commerce vocabulary, and numeral conversion.

The alias table lets lexical retrieval match a question asked in one language
against knowledge written in another without any model. It is deliberately
small and domain-specific; it is a floor, not the ceiling.
"""

from __future__ import annotations

import re

_EASTERN = "٠١٢٣٤٥٦٧٨٩"
_FULLWIDTH = "０１２３４５６７８９"
_WESTERN = "0123456789"

ALIASES: dict[str, set[str]] = {
    "order": {"orders", "pedido", "pedidos", "commande", "bestellung", "طلب", "طلبي", "طلبية",
              "注文", "encomenda"},
    "shipping": {"ship", "ships", "shipped", "delivery", "deliver", "delivered", "arrive",
                 "arrives", "dispatch", "dispatched", "envío", "envio", "envían", "envian",
                 "envía", "envia", "enviáis", "enviais", "enviado", "enviada", "enviam",
                 "enviar", "entrega", "expédition", "expédié", "expédiée", "expédiez",
                 "expedie", "livraison", "versand", "verschickt", "versendet",
                 "lieferung", "شحن", "الشحن", "توصيل", "يوصل", "بيوصل", "وصول", "配送", "配達",
                 "発送", "llega", "chega", "ankommt"},
    "tracking": {"track", "seguimiento", "rastreo", "rastreio", "rastreamento", "suivi",
                 "sendungsverfolgung", "sendungsnummer", "تتبع", "追跡"},
    "return": {"returns", "devolución", "devolucion", "devolver", "devolução", "devolucao",
               "retour", "retourner", "rückgabe", "rueckgabe", "rückgabefrist", "rueckgabefrist",
               "zurückgeben", "إرجاع", "ارجاع",
               "الإرجاع", "الارجاع", "ترجيع", "أرجع", "ارجع", "رجعت", "رجّعت", "ترجع", "返品"},
    "refund": {"refunds", "reembolso", "remboursement", "rückerstattung", "rueckerstattung",
               "استرداد", "الاسترداد", "استرجاع", "الاسترجاع", "المبلغ", "مبلغ", "فلوس",
               "الفلوس", "返金"},
    "policy": {"política", "politica", "politique", "richtlinie", "سياسة", "ポリシー"},
    "days": {"day", "días", "dias", "jours", "tage", "أيام", "ايام", "يوم", "日"},
    "when": {"cuándo", "cuando", "quando", "quand", "wann", "متى", "إمتى", "امتى", "いつ"},
    "price": {"prices", "precio", "preço", "preco", "prix", "preis", "سعر", "السعر", "価格"},
    "size": {"sizes", "talla", "tallas", "tamanho", "tamanhos", "taille", "tailles", "größe",
             "groesse", "grösse", "مقاس", "المقاس", "مقاسات", "حجم", "الحجم", "أحجام", "احجام",
             "الأحجام", "الاحجام", "لتر", "litre", "litres", "liter", "liters", "litros",
             "サイズ"},
    "warranty": {"garantía", "garantia", "garantie", "ضمان", "الضمان", "保証", "保証期間"},
    "hours": {"hour", "horario", "horário", "horaires", "öffnungszeiten", "erreichbar",
              "ساعات", "أوقات", "الأوقات", "مواعيد", "المواعيد", "営業時間", "時間"},
    "support": {"soporte", "atención", "atencion", "suporte", "atendimento", "apoio",
                "assistance", "kundendienst", "kundenservice", "دعم", "الدعم", "サポート",
                "問い合わせ"},
    "weekend": {"weekends", "fin de semana", "fim de semana", "week-end", "wochenende",
                "عطلة", "الويكند", "週末"},
    "laptop": {"laptops", "notebook", "portátil", "portatil", "computadora", "ordenador",
               "ordinateur", "حاسوب", "لابتوب", "لاب", "كمبيوتر", "ノートパソコン",
               "パソコン"},
    "customs": {"aduana", "alfândega", "alfandega", "douane", "zoll", "جمارك", "الجمارك",
                "関税"},
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
_AR_SUFFIXES = ("ها", "هم", "كم", "نا", "ه", "ك", "ي")


def canon(token: str) -> str:
    if token in _INDEX:
        return _INDEX[token]
    if token.endswith("s") and token[:-1] in _INDEX:
        return _INDEX[token[:-1]]
    for pre in _AR_PREFIXES:
        rest = token[len(pre):]
        if token.startswith(pre) and rest in _INDEX:
            return _INDEX[rest]
    for suf in _AR_SUFFIXES:
        rest = token[:-len(suf)]
        if token.endswith(suf) and len(rest) > 2 and rest in _INDEX:
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


_CJK = re.compile(r"[぀-ヿ一-鿿]")
# Single characters ("日") are too ambiguous inside a run of text (日本 is Japan).
_CJK_ALIASES = sorted((a for a in _INDEX if _CJK.search(a) and len(a) > 1), key=len,
                      reverse=True)


def _cjk_heads(run: str) -> set[str]:
    """Japanese has no spaces; find alias words inside a run of CJK text."""
    return {_INDEX[a] for a in _CJK_ALIASES if a in run}


def tokens(text: str) -> set[str]:
    out = set()
    for raw in re.findall(r"\w+", text.lower()):
        c = canon(raw)
        if c in ALIASES:
            out.add(c)
        elif _CJK.search(raw) and (heads := _cjk_heads(raw)):
            out |= heads
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
        heads = [c] if c in ALIASES else (sorted(_cjk_heads(tok)) if _CJK.search(tok) else [])
        for h in heads:
            if h not in out:
                out.append(h)
    return out


def to_eastern(text: str) -> str:
    return text.translate(str.maketrans(_WESTERN, _EASTERN))


def to_western(text: str) -> str:
    """Eastern Arabic and full-width digits to ASCII digits."""
    return text.translate(str.maketrans(_EASTERN + _FULLWIDTH, _WESTERN + _WESTERN))


_NUMBER = re.compile(r"(?<!\d)(?<!\d[.,])\d+(?:[.,]\d+)*(?![.,]?\d)")


def numbers(text: str) -> set[str]:
    """Numeric tokens in the text, digits normalized, leading zeros dropped.

    Dates and times fall apart into their components ("2024-05-01" and
    "01/05/2024" give the same set), which is what a reformatting rewrite
    should be allowed to do without being called a drift.
    """
    out: set[str] = set()
    for m in _NUMBER.findall(to_western(text)):
        for part in re.split(r"[.,]", m):
            part = part.lstrip("0") or "0"
            out.add(part)
    return out


def has_value(text: str, value: str) -> bool:
    """Is the value in the text? Numbers must match as whole tokens, so "30"
    is not found in "#3030"; anything else is a case-insensitive substring."""
    t = to_western(text).lower()
    v = to_western(value).strip().lower()
    if not v:
        return False
    if re.fullmatch(r"\d+(?:[.,]\d+)*", v):
        return re.search(rf"(?<!\d)(?<!\d[.,]){re.escape(v)}(?![.,]?\d)", t) is not None
    return v in t


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
