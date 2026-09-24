from collections import Counter

from envoy.evalset import SETS, demo_samples, heldout_samples, load
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
    assert len(load("all")) == len(demo) + len(heldout_samples())
    assert SETS == ("demo", "heldout", "all")
