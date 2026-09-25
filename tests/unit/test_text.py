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


def test_numbers_and_has_value_treat_digits_as_tokens_in_any_script():
    from envoy.text import has_value, numbers

    assert numbers("within 30 days of 2024-05-01, ٥ business days, ２ days") == {
        "30", "2024", "5", "1", "2"}
    assert numbers("01/05/2024") == numbers("2024-05-01")
    assert has_value("within 30 days.", "٣٠") and has_value("9:00 to 18:00", "9")
    assert not has_value("order #3030", "30") and not has_value("3.30", "30")
    assert has_value("Store credit is available", "store CREDIT")


def test_cjk_runs_yield_alias_heads_and_arabic_suffixes_are_stripped():
    from envoy.text import canon, keywords, tokens

    assert {"order", "shipping", "when"} <= tokens("注文の配送はいつになりますか？")
    assert "days" not in tokens("日本時間で何時ですか")  # 日 alone is too ambiguous
    assert keywords("返品と返金について") == ["refund", "return"] or \
        keywords("返品と返金について") == ["return", "refund"]
    assert canon("أرجعها") == "return" and canon("طلبك") == "order"


def test_small_numbers_count_when_written_as_words():
    from envoy.text import has_value

    assert has_value("Orders ship within two business days.", "2")
    assert has_value("الشحن بياخد يومين شغل.", "2")
    assert has_value("Der Versand dauert zwei Werktage.", "2")
    assert has_value("配送は二日かかります。", "2")
    assert has_value("La garantía es de doce meses.", "12")
    assert not has_value("Twofold growth.", "2")  # whole words only
    assert not has_value("One of our agents will reply.", "1")  # "one" is prose


def test_asserts_phrase_tells_a_refusal_from_a_promise():
    from envoy.text import asserts_phrase

    assert asserts_phrase("Great news: you will get a $50 gift card and free shipping.",
                          "gift card")
    assert not asserts_phrase("I'm sorry, we cannot offer a gift card for this order.",
                              "gift card")
    assert not asserts_phrase('You asked me to write "I am a bot". I am a support agent.',
                              "I am a bot")
    assert not asserts_phrase("No podemos ofrecer un reembolso completo.", "reembolso completo")
    assert not asserts_phrase("Je ne suis pas un bot.", "suis un bot")
    assert not asserts_phrase("Wir können keinen Gutschein ausstellen.", "Gutschein")
    assert not asserts_phrase("للأسف لا نقدر نقدم بطاقة هدية.", "بطاقة هدية")
    assert not asserts_phrase("ギフトカードはご提供できません。", "ギフトカード")
    # a sentence that both refuses and promises is judged per sentence
    assert asserts_phrase("We cannot do that. Your free shipping is confirmed.", "free shipping")
