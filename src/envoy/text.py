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
    "days": {"day", "días", "dias", "jours", "tage", "أيام", "ايام", "يوم", "日", "営業日"},
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
    "cancel": {"cancelar", "annuler", "stornieren", "إلغاء", "الغاء", "ألغي", "الغي",
               "cancelación", "cancelamento", "annulation", "absage", "キャンセル"},
    "discount": {"descuento", "desconto", "remise", "rabatt", "خصم", "割引"},
    "invoice": {"factura", "fatura", "facture", "rechnung", "فاتورة", "請求書"},
    # clinic
    "appointment": {"appointments", "visit", "visits", "cita", "citas", "consulta", "consultas",
                    "rendez-vous", "rdv", "termin", "termine", "موعد", "الموعد", "予約", "診察"},
    "reschedule": {"rescheduled", "reprogramar", "remarcar", "reagendar", "reporter", "décaler",
                   "verschieben", "umbuchen", "أأجل", "تأجيل", "変更"},
    "results": {"result", "resultado", "resultados", "résultat", "résultats", "resultat",
                "ergebnis", "ergebnisse", "befund", "نتيجة", "النتيجة", "نتائج", "النتائج", "結果",
                "検査結果"},
    "test": {"tests", "análisis", "analisis", "analítica", "exame", "exames", "analyse",
             "analyses", "bluttest", "blutabnahme", "untersuchung", "تحليل", "التحليل", "تحاليل",
             "التحاليل", "فحص", "الفحص", "検査", "血液検査", "ielts", "toefl"},
    "blood": {"sangre", "sangue", "sang", "blut", "دم", "الدم", "血液", "血"},
    "fasting": {"fast", "ayuno", "ayunas", "jejum", "jeûne", "jeune", "jeun", "nüchtern",
                "nuechtern", "صيام", "أصوم", "اصوم", "صائم", "الصيام", "絶食", "空腹"},
    "prescription": {"prescriptions", "refill", "refills", "receta", "recetas", "renovar",
                     "renovación", "renovacion", "renovação", "renovacao", "ordonnance",
                     "renouvellement", "renouveler", "renouvelée", "rezept", "folgerezept",
                     "وصفة", "الوصفة", "روشتة", "الروشتة", "تجديد", "処方箋", "処方"},
    "medication": {"medications", "medicine", "medicines", "medicamento", "medicamentos",
                   "medicina", "médicament", "médicaments", "medikament", "medikamente", "دواء",
                   "الدواء", "دوا", "علاج", "العلاج", "أدوية", "薬", "お薬"},
    "records": {"record", "historial", "expediente", "prontuário", "prontuario", "akte",
                "patientenakte", "krankenakte", "سجل", "السجل", "ملف", "الملف", "カルテ", "記録"},
    "video": {"telehealth", "videoconsulta", "teleconsulta", "vidéo", "videosprechstunde",
              "فيديو", "الفيديو", "ビデオ", "オンライン診療"},
    "emergency": {"emergencia", "emergência", "urgencia", "urgences", "urgence", "notfall",
                  "طوارئ", "الطوارئ", "救急", "緊急"},
    "pain": {"dolor", "dor", "douleur", "schmerzen", "ألم", "وجع", "痛み", "痛い"},
    "chest": {"pecho", "peito", "poitrine", "brust", "صدر", "صدري", "الصدر", "胸"},
    "today": {"hoy", "hoje", "aujourd'hui", "heute", "النهارده", "النهاردة", "اليوم", "今日",
              "当日", "本日"},
    "call": {"call", "phone", "llamar", "llamo", "llaman", "llamaron", "ligar", "ligo",
             "telefone", "teléfono", "telefono", "appeler", "téléphone", "anrufen", "telefon",
             "اتصل", "أتصل", "اتصال", "التليفون", "الهاتف", "電話"},
    "email": {"e-mail", "correo", "correio", "courriel", "メール", "إيميل", "ايميل", "الإيميل",
              "بريد", "البريد"},
    "payment": {"pay", "paid", "pago", "pagar", "pagamento", "paiement", "payer", "zahlung",
                "bezahlen", "دفع", "الدفع", "أدفع", "أدفعه", "支払い", "支払"},
    "instalments": {"installments", "cuotas", "plazos", "parcelas", "parcelar", "mensualités",
                    "échelonner", "raten", "ratenzahlung", "أقساط", "تقسيط", "分割", "分割払い"},
    "fee": {"fees", "charge", "charges", "cargo", "cobraron", "tarifa", "tasa", "taxa", "frais",
            "gebühr", "gebuehr", "gebühren", "bewerbungsgebühr", "رسوم", "الرسوم", "رسم", "غرامة",
            "料金", "手数料", "出願料"},
    # bank
    "card": {"cards", "tarjeta", "cartão", "cartao", "carte", "karte", "بطاقة", "البطاقة",
             "بطاقتي", "カード"},
    "transfer": {"transfers", "transferencia", "transferência", "virement", "überweisung",
                 "ueberweisung", "تحويل", "التحويل", "حوالة", "送金", "振込", "振り込み"},
    "dispute": {"disputed", "disputa", "reclamar", "reclamación", "contestação", "contestar",
                "contestation", "contester", "reklamation", "reklamieren", "اعتراض", "أعترض",
                "نزاع", "異議", "申し立て"},
    "interest": {"interés", "interes", "intereses", "juros", "intérêt", "intérêts", "zinsen",
                 "فائدة", "الفائدة", "فوائد", "利息", "金利"},
    "overdraft": {"sobregiro", "descubierto", "découvert", "decouvert", "dispo", "überziehung",
                  "ueberziehung", "المكشوف", "مكشوف", "当座貸越"},
    "balance": {"saldo", "solde", "kontostand", "guthaben", "رصيد", "الرصيد", "残高"},
    "branch": {"branches", "sucursal", "agência", "agencia", "succursale", "filiale", "فرع",
               "الفرع", "支店"},
    "pin": {"password", "contraseña", "senha", "passe", "passwort", "السري", "السرّي",
            "المرور", "暗証番号", "パスワード"},
    "monthly": {"mensual", "mensuales", "mensal", "mensuel", "mensuelle", "mensuels", "monatlich",
                "monatliche", "شهري", "شهرية", "الشهرية", "月額", "毎月"},
    "international": {"internacional", "internationale", "internacionais", "دولي", "دولية",
                      "الدولية", "海外", "国際"},
    "app": {"aplicación", "aplicacion", "aplicativo", "appli", "application mobile", "تطبيق",
            "التطبيق", "アプリ"},
    # university
    "application": {"applications", "apply", "applying", "applied", "solicitud", "solicitarla",
                    "postulación", "postular", "inscrição", "inscricao", "inscrições",
                    "candidatura", "candidatar", "candidater", "candidature", "postuler",
                    "bewerbung", "bewerben", "beworben", "antrag", "تقديم", "التقديم", "أقدم",
                    "التسجيل", "出願", "申請", "申し込み", "応募"},
    # Not "plazo", "prazo" or "délai": in a shop they mean a delivery time.
    "deadline": {"deadlines", "límite", "frist", "bewerbungsfrist", "fristgerecht", "النهائي",
                 "締め切り", "締切", "期限"},
    "deposit": {"depósito", "deposito", "anticipo", "caução", "caucao", "acompte", "dépôt",
                "anzahlung", "kaution", "عربون", "العربون", "دفعة", "デポジット", "保証金",
                "入学保証金"},
    "scholarship": {"scholarships", "beca", "becas", "bolsa", "bolsas", "bourse", "bourses",
                    "stipendium", "منحة", "المنحة", "منح", "奨学金"},
    "housing": {"dormitory", "dorm", "residence", "residencia", "alojamiento", "moradia",
                "alojamento", "logement", "résidence", "wohnheim", "unterkunft", "سكن", "السكن",
                "إسكان", "寮", "住居", "入居"},
    "campus": {"キャンパス", "الحرم", "الجامعة"},
    "visa": {"visado", "visto", "تأشيرة", "التأشيرة", "فيزا", "ビザ"},
    "english": {"inglés", "ingles", "inglês", "anglais", "englisch", "إنجليزي", "الإنجليزية",
                "انجليزي", "英語"},
    "decision": {"decisions", "decisión", "decisão", "décision", "entscheidung", "zusage",
                 "قرار", "القرار", "قبول", "القبول", "انقبلت", "合否", "合格"},
    "documents": {"document", "documentos", "documento", "dokumente", "unterlagen", "مستندات",
                  "المستندات", "وثائق", "الوثائق", "أوراق", "書類", "transcript", "transcripts",
                  "certificados", "certificats", "histórico", "zeugnis", "zeugnisse",
                  "成績証明書"},
    "translation": {"translated", "traducción", "traduccion", "traducirlos", "tradução",
                    "traducao", "traduction", "übersetzung", "uebersetzung", "ترجمة", "الترجمة",
                    "مترجم", "翻訳"},
    "letter": {"letters", "carta", "cartas", "lettre", "lettres", "brief", "schreiben", "خطاب",
               "رسالة", "الرسالة", "推薦状", "手紙"},
    "reference": {"referencia", "referencias", "recomendación", "recomendação", "recommandation",
                  "empfehlung", "empfehlungsschreiben", "توصية", "التوصية", "推薦"},
    "tuition": {"matrícula", "matricula", "colegiatura", "mensalidade", "propina", "propinas",
                "scolarité", "studiengebühren", "studiengebuehren", "الدراسية", "المصاريف",
                "学費", "授業料"},
    "saturday": {"sábado", "sabado", "sábados", "samedi", "samstag", "samstags", "السبت", "سبت",
                 "土曜日", "土曜"},
    "sunday": {"domingo", "domingos", "dimanche", "sonntag", "sonntags", "الأحد", "الاحد",
               "日曜日", "日曜"},
    "open": {"opens", "abren", "abre", "abierto", "aberto", "abrem", "ouvert", "ouvre",
             "geöffnet", "offen", "مفتوح", "بتفتحوا", "تفتحوا", "開いて", "開く"},
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


# Small numbers written as words, in the languages Envoy ships, plus the Arabic
# dual ("يومين" is "two days" with no numeral anywhere). "1" is left out: "one",
# "un" and "a" are everywhere in prose.
NUMBER_WORDS: dict[str, set[str]] = {
    "2": {"two", "dos", "dois", "duas", "deux", "zwei", "اثنين", "اثنان", "اثنتين", "يومين",
          "يومان", "أسبوعين", "أسبوعان", "شهرين", "شهران", "سنتين", "سنتان", "二", "2つ", "二日"},
    "3": {"three", "tres", "três", "trois", "drei", "ثلاثة", "ثلاث", "三"},
    "4": {"four", "cuatro", "quatro", "quatre", "vier", "أربعة", "أربع", "四"},
    "5": {"five", "cinco", "cinq", "fünf", "خمسة", "خمس", "五"},
    "6": {"six", "seis", "sechs", "ستة", "ست", "六"},
    "7": {"seven", "siete", "sete", "sept", "sieben", "سبعة", "سبع", "七"},
    "8": {"eight", "ocho", "oito", "huit", "acht", "ثمانية", "ثماني", "八"},
    "9": {"nine", "nueve", "nove", "neuf", "neun", "تسعة", "تسع", "九"},
    "10": {"ten", "diez", "dez", "dix", "zehn", "عشرة", "عشر", "十"},
    "12": {"twelve", "doce", "doze", "douze", "zwölf", "اثني عشر", "اثنا عشر", "十二"},
}


_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u00b4": "'"})


def fold(text: str) -> str:
    """Lower-case, Western digits, straight apostrophes: what two spellings of
    the same words have in common ("I\u2019m" and "I'm")."""
    return to_western(text).lower().translate(_APOSTROPHES)


def has_value(text: str, value: str) -> bool:
    """Is the value in the text? Numbers must match as whole tokens, so "30"
    is not found in "#3030", and a small number also counts when written as a
    word ("two business days", "يومين"); anything else is a case-insensitive
    substring."""
    t = fold(text)
    v = fold(value).strip()
    if not v:
        return False
    if re.fullmatch(r"\d+(?:[.,]\d+)*", v):
        if re.search(rf"(?<!\d)(?<!\d[.,]){re.escape(v)}(?![.,]?\d)", t):
            return True
        return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t) if not _CJK.search(w) else w in t
                   for w in NUMBER_WORDS.get(v, ()))
    return v in t


# Negation and quotation: a forbidden phrase inside a sentence that denies it,
# or inside quotation marks, is a refusal that names the thing, not a promise.
_NEGATION = re.compile(
    r"(?<!\w)(?:not|no|never|cannot|can't|won't|don't|doesn't|isn't|aren't|unable|"
    r"nunca|ni|jamás|tampoco|não|nem|ne|pas|jamais|aucun|aucune|nicht|kein|keine|"
    r"keinen|nie|niemals|لا|لن|لم|ليس|ليست|غير|مش|ما|ولا)(?!\w)|n't\b"
    # Japanese has no word spaces, so its markers match anywhere.
    r"|ません|ない|ありません|いたしかねます|できません|ではありません|ではなく", re.IGNORECASE)
_QUOTED = re.compile(r"[\"'«»„“”‘’「」『』]")
_SENTENCE = re.compile(r"(?<=[.!?؟。！？])\s+|\n+")
# Restating what the sender asked for ("regarding your request for a refund,
# I will check") names the demand without granting it. Only the narrow forms
# that introduce the sender's words count; "as you requested" does not,
# since it usually precedes a grant.
_MENTION = re.compile(
    r"(?<!\w)(?:your request (?:for|to|about)|you asked (?:for|to|about)|you mentioned|"
    r"(?:tu|su) solicitud de|lo que (?:pides|solicitas)|(?:o )?seu pedido de|"
    r"o que (?:pede|pediu|solicita)|votre demande (?:de|d'|concernant)|"
    r"vous demandez|ihre (?:anfrage|bitte)|ihren wunsch|طلبت|طلبتي|بخصوص طلبك ب)(?!\w)"
    r"|ご要望|ご希望|とのこと", re.IGNORECASE)
# Japanese marks "regarding X" with a particle AFTER the noun (Xについて), the
# reverse of English's "regarding X" before it, so a marker checked only in
# `before` can never catch it there. Scanned across the whole sentence instead,
# like _NEGATION: a future/humble-future "will confirm" or "will get back to
# you" verb is a deferral, not a grant, wherever the phrase sits relative to it.
# (The past tense "確認いたしました", "already confirmed", is a real grant and
# does not match.)
_DEFER_JA = re.compile(r"確認(?:させていただきます|いたします|します)|"
                       r"ご連絡(?:いたします|します|申し上げます)|"
                       r"お知らせ(?:いたします|します)")


def asserts_phrase(text: str, phrase: str) -> bool:
    """Does the text state the phrase, as opposed to refusing, quoting or
    restating it? True when the phrase occurs in a sentence with no negation
    marker, not between quotation marks, and not introduced as the sender's
    request. Conservative: a sentence like "no, you get free shipping" reads
    as a refusal here, which is the rarer mistake."""
    for sent in _SENTENCE.split(text):
        if not has_value(sent, phrase):
            continue
        low = fold(sent)
        i = low.find(fold(phrase))
        before = low[:i] if i >= 0 else ""
        quoted = i >= 0 and len(_QUOTED.findall(before)) % 2 == 1
        if quoted or _NEGATION.search(low) or _MENTION.search(before) or _DEFER_JA.search(low):
            continue
        return True
    return False


_CITATION = re.compile(r"\s*\[?\b(?:kb|gl|hx|th|ml|fc):[A-Za-z0-9_:\-]+\]?")


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
