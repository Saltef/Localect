import asyncio
from pathlib import Path

from localect.config import Settings
from localect.evalx import flores, massive
from localect.models.base import FakeModel
from localect.schemas import Reading

FIX = Path(__file__).parent.parent / "fixtures"


def _settings():
    return Settings(provider="stub", user_name="Safea", user_language="en")


# --- MASSIVE -------------------------------------------------------------------


def test_massive_loader_reads_the_partition_and_parses_slots():
    utts = massive.load_massive(FIX / "massive", ["ar", "en"], n=10)
    assert {u.language for u in utts} == {"ar", "en"}
    assert all(u.locale in ("ar-SA", "en-US") for u in utts)
    ids = {u.id for u in utts}
    assert "4" not in ids and "14" not in ids, "only the test partition"
    en = next(u for u in utts if u.id == "12")
    assert en.slots == [("person", "Maria"), ("business_name", "Nadir Goods"), ("date", "monday")]
    assert massive.parse_slots("weck mich [date : diese woche] um [time : fünf uhr] auf") == [
        ("date", "diese woche"), ("time", "fünf uhr")]
    assert massive.load_massive(FIX / "massive", ["fr"], n=10) == []
    assert len(massive.load_massive(FIX / "massive", ["en"], n=2)) == 2


def test_reader_scoring_distinguishes_strict_from_lenient_recall():
    utt = massive.load_massive(FIX / "massive", ["en"], n=10)
    u = next(x for x in utt if x.id == "12")
    reading = Reading(language="en", gloss="book a meeting with Maria at Nadir Goods on monday",
                      intent="book a meeting", asks=[], must_preserve=["Maria", "Nadir Goods"])
    row = massive.score_reading(reading, u)
    assert row.language_ok and (row.slots, row.slots_strict, row.slots_lenient) == (3, 2, 3)
    assert row.missed == []
    reading = Reading(language="fr", gloss="", intent="", must_preserve=[])
    row = massive.score_reading(reading, u)
    assert not row.language_ok and row.slots_strict == 0 and len(row.missed) == 3


def test_massive_runs_on_the_stub_and_renders():
    rows = asyncio.run(massive.run_massive(_settings(), FIX / "massive", ["ar", "en"], n=10))
    assert len(rows) == 8 and all(r.model == "stub" and not r.error for r in rows)
    en = [r for r in rows if r.language == "en"]
    assert all(r.language_ok for r in en)
    email = next(r for r in en if r.id == "11")
    assert email.slots_strict == 1, "the stub's preserve regex finds the email address"
    table = massive.render_massive(rows)
    assert "Reader on MASSIVE, stub" in table and "\n  ar " in table and "\n  en " in table
    assert massive.massive_to_dicts(rows)[0]["language"] in ("ar", "en")


# --- FLORES --------------------------------------------------------------------


def test_chrf_matches_known_values():
    assert flores.chrf("the cat sat", "the cat sat") == 100.0
    assert flores.chrf("", "the cat sat") == 0.0
    assert flores.chrf("completely different words here", "zzzz") == 0.0
    a = flores.chrf("The parcel leaves the warehouse in two days.",
                    "The parcel leaves the warehouse within two business days.")
    b = flores.chrf("Something else entirely.",
                    "The parcel leaves the warehouse within two business days.")
    assert 50 < a < 100 and b < a
    # Corpus level: accumulated counts, not an average of sentence scores.
    corpus = flores.chrf_corpus([("the cat sat", "the cat sat"), ("x", "the dog ran far away")])
    assert 0 < corpus < 100


def test_flores_loader_pairs_sources_with_english_references():
    pairs = flores.load_pairs(FIX / "flores", "ar", n=2)
    assert len(pairs) == 2 and all(len(p) == 3 for p in pairs)
    i, src, ref = pairs[0]
    src_all = (FIX / "flores/devtest/arb_Arab.devtest").read_text(encoding="utf-8").splitlines()
    ref_all = (FIX / "flores/devtest/eng_Latn.devtest").read_text(encoding="utf-8").splitlines()
    assert src == src_all[i] and ref == ref_all[i]
    assert flores.load_pairs(FIX / "flores", "ja", n=2) == []


def test_flores_runs_the_critic_and_scores_its_back_translation():
    from localect.pipeline import _fallback_locale

    ref = "The parcel leaves the warehouse within two business days."
    fake = FakeModel([f'{{"back_segments": [{{"id": "s1", "text": "{ref}"}}], "flags": []}}'])
    hyp = asyncio.run(flores.back_translate(fake, "يغادر الطرد", _fallback_locale("ar"),
                                            "English"))
    assert hyp == ref and flores.chrf(hyp, ref) == 100.0
    assert fake.calls[0]["role"] == "critic"
    table = flores.render_flores([
        flores.BackScore(model="fake", language="ar", index=0, source="x", reference=ref,
                         hypothesis=ref, chrf=100.0),
        flores.BackScore(model="fake", language="pt", index=0, source="x", reference=ref,
                         hypothesis="zzz", chrf=0.0)])
    assert "\n  ar " in table and "ok" in table and "LOW" in table


def test_flores_on_the_stub_reports_per_language():
    rows = asyncio.run(flores.run_flores(_settings(), FIX / "flores", ["ar", "pt"], n=3))
    assert len(rows) == 6 and all(not r.error for r in rows)
    assert {r.language for r in rows} == {"ar", "pt"}
    assert all(0 <= r.chrf <= 100 for r in rows)
    assert "Critic back-translation on FLORES-200" in flores.render_flores(rows)
