from envoy.text import canon, keywords, to_eastern, to_western, tokens


def test_canon_aliases_and_plurals():
    assert canon("pedido") == "order"
    assert canon("orders") == "order"
    assert canon("الإرجاع") == "return"
    assert canon("بيوصل") == "shipping"
    assert canon("والشحن") == "shipping"
    assert canon("banana") == "banana"


def test_tokens_cross_lingual_overlap():
    ask = tokens("متى بيوصل طلبي؟")
    kb = tokens("Orders ship within 2 business days.")
    assert {"order", "shipping"} <= (ask & kb)


def test_keywords_in_order():
    assert keywords("Quando chega meu pedido e a política de devolução?") == [
        "when", "shipping", "order", "policy", "return"]


def test_numerals_roundtrip():
    assert to_eastern("30 days #4521") == "٣٠ days #٤٥٢١"
    assert to_western("٣٠") == "30"
