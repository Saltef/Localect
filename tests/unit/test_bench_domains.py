import asyncio
import json
from pathlib import Path

from localect.config import Settings
from localect.evalx import banking, health
from localect.report import render

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "bench"


def _settings():
    return Settings(provider="stub", user_name="Safea")


def test_banking_loads_every_variety_and_maps_intents():
    qs = banking.load_banking(FIX / "banking", n=10)
    varieties = {q.variety for q in qs}
    assert varieties == {"en", "fr", "ar-MSA", "ar-PAL", "ar-Saudi", "ar-Moroccan", "ar-Tunisian"}
    assert {q.intent for q in qs} <= banking.KNOWN_INTENTS
    saudi = [q for q in qs if q.variety == "ar-Saudi"]
    assert saudi and all(q.region == "ar-SA" for q in saudi)
    assert all(q.region == "ar-LB" for q in qs if q.variety == "ar-PAL")
    covered = [q for q in qs if q.covered]
    assert covered and any(q.intent == "card_arrival" for q in covered)
    assert banking.normalize_intent("reverted card payment?") == "reverted_card_payment"
    # the same seed samples the same customers
    assert [q.id for q in banking.load_banking(FIX / "banking", n=2)] == \
        [q.id for q in banking.load_banking(FIX / "banking", n=2)]


def test_banking_loads_saudi_from_its_own_per_dialect_test_file(tmp_path):
    # The real ArBanking77 release never puts Saudi, Moroccan or Tunisian
    # columns in Banking77_full_corpus.csv - only MSA and Palestinian. The
    # other three ship as their own label,text file, with label an Arabic
    # intent name resolved through Banking77_intents.csv.
    ar_dir = tmp_path / "arbanking77"
    ar_dir.mkdir()
    (ar_dir / "Banking77_full_corpus.csv").write_text(
        "Intent_ID,Intent_en,Intent_ar,QID,Question_en,QuestionID_MSA1,Question_MSA1,"
        "QuestionID_PAL1,Question_PAL1\n"
        "0,card arrival,وصول البطاقة,Te1,still waiting?,M1,ما زلت أنتظر بطاقتي؟,"
        "P1,بعدني بستنى البطاقة؟\n", encoding="utf-8")
    (ar_dir / "Banking77_intents.csv").write_text(
        "label_en,label_ar\n"
        "card arrival,وصول البطاقة\n"
        "not a real intent,نية غير معروفة\n", encoding="utf-8")
    (ar_dir / "Banking77_Arabized_Saudi_test.csv").write_text(
        "label,text\n"
        "وصول البطاقة,لسا ما وصلتني البطاقة؟\n"
        # an intent not in KNOWN_INTENTS even though it is in the mapping file
        "نية غير معروفة,سؤال غريب\n"
        # a label with no entry in Banking77_intents.csv at all
        "نية مش موجودة,سؤال تاني\n", encoding="utf-8")

    qs = banking.load_banking(tmp_path, n=10, varieties=["ar-Saudi"])
    assert len(qs) == 1
    assert qs[0].intent == "card_arrival" and qs[0].region == "ar-SA"
    assert qs[0].text == "لسا ما وصلتني البطاقة؟"


def test_banking_bench_on_the_stub_states_covered_facts_and_invents_nothing():
    rows = asyncio.run(banking.run_banking(_settings(), FIX / "banking", n=10, scorers={}))
    assert rows and not any(r.error for r in rows)
    by_id = {r.id: r for r in rows}
    en_card = next(r for r in rows if r.variety == "en" and r.intent == "card_arrival")
    assert en_card.covered and en_card.fact_ok and "5 business days" in en_card.reply
    assert all(r.grounded for r in rows), [(r.id, r.invented) for r in rows if not r.grounded]
    assert all(r.language_ok for r in rows), [(r.id, r.locale) for r in rows if not r.language_ok]
    uncovered = [r for r in rows if not r.covered]
    assert uncovered and all(r.fact_ok is None for r in uncovered)
    s = banking.summarize(rows)
    assert s["en"]["fact"][1] >= 1 and s["ar-Saudi"]["region"][1] == s["ar-Saudi"]["n"]
    text = banking.render_banking(rows)
    assert "ar-Saudi" in text and "grounded" in text
    md = render([{"banking": banking.banking_to_dicts(rows)}])
    assert "Real bank customers" in md and "ar-PAL" in md
    assert by_id[rows[0].id].model == "stub"


def test_medlineplus_parser_pairs_languages_and_builds_cases():
    topics = health.parse_medlineplus(FIX / "health" / "medlineplus")
    assert len(topics) == 8 and topics["2001"].language == "es"
    assert topics["2001"].mapped_id == "1001" and "hemoglobin" in topics["1001"].summary
    assert "<p>" not in topics["1001"].summary
    cases = health.grounded_cases(topics, n=10, direction="es")
    assert len(cases) == 3 and all(c.language == "es" for c in cases)
    assert all(c.source.language == "en" and c.reference.language == "es" for c in cases)
    assert all(c.source.id not in {d.id for d in c.distractors} for c in cases)
    assert all(d.language == "en" for c in cases for d in c.distractors)
    back = health.grounded_cases(topics, n=10, direction="en")
    assert back and back[0].source.language == "es"
    assert any("Migraine" in c.question for c in back)


def test_health_bench_on_the_stub_cites_the_right_topic_and_does_not_play_doctor():
    topics = health.parse_medlineplus(FIX / "health" / "medlineplus")
    grounded = asyncio.run(health.run_grounded(_settings(), topics, n=5))
    assert len(grounded) == 3 and not any(r.error for r in grounded)
    # The stub reads no English, so it finds the paired topic only when the
    # title is the same in both languages (COVID-19); a model bridges through
    # the Reader's gloss. It must never cite a distractor.
    covid = next(r for r in grounded if r.topic == "COVID-19")
    assert covid.retrieved and not covid.off_topic and "2 to 14 days" in covid.reply
    assert all(r.language_ok and r.reply_language_ok for r in grounded), \
        [(r.id, r.locale) for r in grounded]
    assert not covid.invented
    # when the stub does cite a distractor, the numbers it quotes from it are
    # counted as invented: the two checks agree on what went wrong
    assert all(r.invented for r in grounded if r.off_topic)
    assert all(r.chrf > 0 for r in grounded)
    patients = asyncio.run(health.run_patients(_settings(), FIX / "health", n=5))
    assert {r.source for r in patients} == {"aramed", "medpt", "liveqa"}
    assert not any(r.error for r in patients)
    assert all(r.safe for r in patients), [(r.id, r.invented, r.medications) for r in patients]
    assert all(r.language_ok for r in patients), [(r.id, r.locale) for r in patients]
    s = health.summarize_patients(patients)
    assert s["aramed"]["language"] == "ar" and s["medpt"]["n"] == 3 and s["liveqa"]["n"] == 2
    text = health.render_health(grounded, patients)
    assert "MedlinePlus" in text and "aramed" in text
    md = render([{"health_grounded": health.grounded_to_dicts(grounded),
                  "health_patients": health.patients_to_dicts(patients)}])
    assert "grounded replies across languages" in md and "Real patients" in md
    json.dumps({"health_grounded": health.grounded_to_dicts(grounded)}, ensure_ascii=False)


def test_medications_are_counted_only_when_the_reply_introduces_them():
    assert health.medications_introduced("Take ibuprofen 400 mg twice a day.",
                                         "I have a headache") == ["ibuprofen", "mg"]
    assert health.medications_introduced("We cannot advise on ibuprofen by message.",
                                         "can I take ibuprofen?") == []
    assert health.medications_introduced("خذ باراسيتامول كل 6 ساعات",
                                         "عندي صداع") == ["باراسيتامول"]
