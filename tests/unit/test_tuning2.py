import httpx
import pytest

from localect.agents.critic import normalize_critique
from localect.models.base import ModelError
from localect.models.cohere import CohereModel
from localect.schemas import Critique
from localect.text import fill_name


def test_retry_on_500_then_success(monkeypatch):
    monkeypatch.setattr("localect.models.cohere.time.sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(500, json={"message": "internal server error"})
        return httpx.Response(200, json={"message": {"content": [{"type": "text", "text": "ok"}]}})

    m = CohereModel("m", "k")
    m._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert m.generate([{"role": "user", "content": "x"}], role="r") == "ok"
    assert len(calls) == 3


def test_no_retry_on_4xx(monkeypatch):
    monkeypatch.setattr("localect.models.cohere.time.sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(401, json={"message": "bad key"})

    m = CohereModel("m", "k")
    m._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ModelError):
        m.generate([], role="r")
    assert len(calls) == 1


def test_normalize_critique_tolerates_near_misses():
    raw = {
        "back_segments": [{"id": "s1", "text": "hi"}, "junk"],
        "flags": [
            {"segment_id": "s1", "kind": "Tone Off", "reason": "stiff"},
            {"segment_id": "s2", "kind": "awkward-phrasing", "reason": "say it simpler"},
            {"segment_id": "s3", "kind": "drifted", "span": "#1", "reason": "lost"},
        ],
    }
    cq = Critique.model_validate(normalize_critique(raw))
    kinds = [(f.segment_id, f.kind.value, f.severity) for f in cq.flags]
    assert kinds == [("s1", "tone_off", "warn"), ("s3", "drifted", "block")]
    assert cq.suggestions[0].segment_id == "s2" and "simpler" in cq.suggestions[0].suggestion
    assert [b.id for b in cq.back_segments] == ["s1"]


def test_fill_name_drops_slot_cleanly():
    assert fill_name("Hi {name},", "", "en") == "Hi there,"
    assert fill_name("Olá, {name}!", "", "pt") == "Olá!"
    assert fill_name("أهلاً {name}،", "", "ar") == "أهلاً،"
    assert fill_name("{name}様\n\nお世話になっております。", "", "ja").startswith("お客様")
    assert fill_name("Hola, {name}:", "Sofía", "es") == "Hola, Sofía:"
