from collections import Counter

from envoy.evalset import SETS, demo_samples, domain_samples, domains, heldout_samples, load
from envoy.locales import load_starter_profiles


def test_held_out_set_covers_every_starter_locale_with_fresh_samples():
    samples = heldout_samples()
    locales = {p.locale for p in load_starter_profiles()}
    counts = Counter(s.locale for s in samples)
    assert set(counts) == locales, "every starter locale has held-out samples"
    assert min(counts.values()) >= 5
    assert len({s.id for s in samples}) == len(samples), "ids are unique"
    assert all(s.set == "heldout" and s.has_expectations for s in samples)
    demo_texts = {s.text for s in demo_samples()}
    assert not demo_texts & {s.text for s in samples}, "held-out samples are not demo samples"


def test_expectations_are_well_formed():
    for s in load("all"):
        assert s.text.strip() and s.label
        assert all(alts and all(a.strip() for a in alts) for alts in s.facts)
        assert not set(v for v in s.wrong) & {a for alts in s.facts for a in alts}


def test_demo_set_is_converted_from_the_demo_messages():
    demo = demo_samples()
    assert [s.id for s in demo][:2] == ["demo-00", "demo-01"]
    assert demo[6].forbid and demo[2].terms == ["SkyPack"] and demo[0].facts == [["30", "٣٠"]]
    assert len(load("all")) == (len(demo) + len(heldout_samples()) + len(load("injection"))
                                + len(domain_samples()))
    assert SETS == ("demo", "heldout", "injection", "domains", "all")


def test_domain_samples_check_only_what_their_own_knowledge_base_states():
    from envoy import db
    from envoy.text import numbers

    kbs = domains()
    assert set(kbs) == {"clinic", "bank", "university"}
    samples = domain_samples()
    counts = Counter((s.domain, s.locale) for s in samples)
    assert set(counts) == {(d, lang) for d in kbs for lang in
                           ("en", "ar", "pt", "es", "fr", "de", "ja")}
    assert min(counts.values()) == 2 and len({s.id for s in samples}) == len(samples)
    assert all(s.set == "domains" and s.has_expectations for s in samples)
    for key, dom in kbs.items():
        kb = " ".join(t for _t, t in dom.knowledge)
        kb_numbers = numbers(kb)
        glossary_terms = {g[0] for g in dom.glossary}
        for s in (x for x in samples if x.domain == key):
            # every wrong value is absent from the whole knowledge base, so a
            # reply that quotes the right paragraph cannot trip it
            assert not set(s.wrong) & kb_numbers, (s.id, s.wrong)
            # a forbidden phrase is never the knowledge base's own wording
            assert not any(f.lower() in kb.lower() for f in s.forbid), s.id
            assert set(s.terms) <= glossary_terms, s.id
        con = db.connect()
        dom.seed(con)
        assert len(db.knowledge_list(con)) == len(dom.knowledge)
        assert {g["term"] for g in db.glossary_list(con)} == glossary_terms
