from collections import Counter

from envoy.evalset import injection_samples, load


def test_injection_set_covers_twenty_attacks_in_every_language():
    samples = injection_samples()
    by_lang = Counter(s.locale for s in samples)
    assert set(by_lang) == {"en", "ar", "pt", "es", "fr", "de", "ja"}
    assert all(n == 20 for n in by_lang.values())
    assert len({s.id for s in samples}) == len(samples)
    assert all(s.forbid and s.facts and "#3030" in s.text or s.facts for s in samples)
    attacks = {s.label.split(", ", 1)[1] for s in samples}
    assert len(attacks) == 20
    assert len(load("all")) == (len(load("demo")) + len(load("heldout")) + len(samples)
                                + len(load("domains")))


def test_forbidden_phrases_do_not_match_the_legitimate_answer():
    """A forbid list that fires on the knowledge base's own wording would
    make every honest reply fail."""
    from envoy.demo import KNOWLEDGE
    from envoy.text import has_value

    kb = " ".join(text for _, text in KNOWLEDGE)
    for s in injection_samples():
        hits = [p for p in s.forbid if has_value(kb, p)]
        assert hits == [], (s.id, hits)
