from envoy.models.stub import detect_language, extract_preserve, guess_region


def test_language_detection():
    assert detect_language("مرحبا، كيفك؟") == "ar"
    assert detect_language("Olá, você pode confirmar o envio?") == "pt"
    assert detect_language("Hola, ¿cuándo llega mi pedido? Gracias") == "es"
    assert detect_language("Bonjour, merci pour votre commande") == "fr"
    assert detect_language("Hallo, ich habe eine Frage zur Bestellung") == "de"
    assert detect_language("こんにちは。注文はいつ届きますか？") == "ja"
    assert detect_language("Hello, when does my order ship?") == "en"


def test_region_guess_uses_whole_words():
    assert guess_region("مرحبا، كيفك؟ وشو سياسة الإرجاع", "ar") == "ar-LB"  # "وشو" is not "وش"
    assert guess_region("ازيك عايز اعرف", "ar") == "ar-EG"
    assert guess_region("شلونك، ابغى اعرف", "ar") == "ar-SA"
    assert guess_region("Olá, você pode confirmar?", "pt") == "pt-BR"
    assert guess_region("Bom dia, estou a aguardar", "pt") == "pt-PT"
    assert guess_region("What colour is it?", "en") == "en-GB"


def test_must_preserve_extraction():
    got = extract_preserve("Order #4521, €120.50, due 2026-09-30, mail a@b.com, ref AB-1234")
    assert {"#4521", "€120.50", "2026-09-30", "a@b.com", "AB-1234"} <= set(got)
