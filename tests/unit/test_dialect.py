from pathlib import Path

import pytest

from envoy.evalx.dialect import (
    MADAR_CITIES,
    NgramModel,
    NgramScorer,
    discover,
    matches,
    normalize_label,
    read_corpus,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "dslcc"


def test_read_corpus_accepts_tab_separated_files_and_label_named_files(tmp_path):
    rows = list(read_corpus(FIXTURE))
    assert len(rows) == 10 and {r[1] for r in rows} == {"pt-BR", "pt-PT"}
    (tmp_path / "CAI.txt").write_text("ازيك عامل ايه\nعايز اعرف\n", encoding="utf-8")
    (tmp_path / "BEI.txt").write_text("كيفك شو الاخبار\n", encoding="utf-8")
    assert sorted(read_corpus(tmp_path)) == [("ازيك عامل ايه", "CAI"), ("عايز اعرف", "CAI"),
                                             ("كيفك شو الاخبار", "BEI")]


def test_ngram_model_trains_predicts_and_round_trips(tmp_path):
    m = NgramModel("pt").train(read_corpus(FIXTURE))
    assert m.labels == ["pt-BR", "pt-PT"] and dict(m.docs) == {"pt-BR": 5, "pt-PT": 5}
    label, margin = m.predict("Estamos a enviar a sua encomenda; receberá o código por correio.")
    assert label == "pt-PT" and margin > 0
    br = "Estamos enviando seu pedido, você recebe o rastreio por e-mail."
    assert m.predict(br)[0] == "pt-BR"
    path = tmp_path / "models" / "dialect-pt.json"
    m.save(path)
    again = NgramModel.load(path)
    assert again.labels == m.labels and again.predict("Você pode devolver em trinta dias.")[0] \
        == m.predict("Você pode devolver em trinta dias.")[0]
    assert NgramModel().predict("anything") == (None, 0.0)


def test_labels_normalize_to_envoy_locales_and_groups():
    assert normalize_label("CAI") == "ar-EG" and normalize_label("BEI") == "ar-LB"
    assert normalize_label("RIY") == "ar-SA" and normalize_label("MSA") == "ar-MSA"
    assert normalize_label("es-ar") == "es-LA" and normalize_label("pt-br") == "pt-BR"
    assert normalize_label("something-else") == "something-else"
    assert matches("pt-PT", "pt-PT") and not matches("pt-BR", "pt-PT")
    assert matches("es-LA", "es-MX") and not matches("es-ES", "es-MX")
    assert not matches("ar-MSA", "ar-EG") and not matches(None, "ar-EG")
    assert set(MADAR_CITIES.values()) >= {"ar-EG", "ar-LB", "ar-SA", "ar-MSA"}


def test_discover_loads_trained_models_from_the_data_dir(tmp_path):
    NgramModel("pt").train(read_corpus(FIXTURE)).save(tmp_path / "models" / "dialect-pt.json")
    scorers = discover(tmp_path)
    assert "pt" in scorers and scorers["pt"].name == "ngram:dialect-pt.json"
    assert scorers["pt"].predict("Estou a tentar devolver a encomenda.") == "pt-PT"
    assert isinstance(scorers["pt"], NgramScorer)
    # Arabic comes from CAMeL Tools only when it is installed with its data.
    pytest.importorskip("camel_tools")
    assert "ar" in scorers


def test_camel_backend_maps_cities_to_locales():
    pytest.importorskip("camel_tools")
    from envoy.evalx.dialect import CamelScorer

    try:
        sc = CamelScorer()
    except Exception as e:  # noqa: BLE001 - data not downloaded
        pytest.skip(f"camel dialectid data not available: {e}")
    assert sc.predict("ازيك يا فندم، الشحن بياخد قد ايه؟") in MADAR_CITIES.values()
