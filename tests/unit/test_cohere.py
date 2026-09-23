import httpx
import pytest
from pydantic import BaseModel

from envoy.config import Settings
from envoy.models import build_model
from envoy.models.base import ModelError
from envoy.models.cohere import CohereModel


def _model(handler, model="command-a-03-2025"):
    m = CohereModel(model, "k")
    m._client = httpx.Client(transport=httpx.MockTransport(handler))
    return m


class S(BaseModel):
    pass


def test_generate_uses_v2_chat_and_reads_text_parts():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = req.read().decode()
        return httpx.Response(200, json={"message": {"role": "assistant", "content": [
            {"type": "text", "text": '{"a":'}, {"type": "text", "text": "1}"}]}})

    out = _model(handler).generate([{"role": "user", "content": "x"}], role="reader", schema=S)
    assert out == '{"a":1}'
    assert seen["path"] == "/v2/chat" and seen["auth"] == "Bearer k"
    assert '"response_format"' in seen["body"] and '"temperature":0' in seen["body"]


def test_generate_retries_without_response_format_on_400():
    calls = []

    def handler(req):
        calls.append("response_format" in req.read().decode())
        if calls[-1]:
            return httpx.Response(400, json={"message": "unsupported"})
        return httpx.Response(200, json={"message": {"content": [{"type": "text", "text": "{}"}]}})

    assert _model(handler).generate([], role="r", schema=S) == "{}"
    assert calls == [True, False]


def test_generate_reports_cohere_error_body():
    def handler(req):
        return httpx.Response(429, json={"message": "rate limited"})

    with pytest.raises(ModelError) as e:
        _model(handler).generate([], role="r")
    assert "429" in str(e.value) and "rate limited" in str(e.value)


def test_list_models_filters_chat_models_and_check_reports_availability():
    def handler(req):
        assert req.url.path == "/v1/models"
        return httpx.Response(200, json={"models": [
            {"name": "command-a-03-2025", "endpoints": ["chat"]},
            {"name": "embed-v4.0", "endpoints": ["embed"]},
            {"name": "c4ai-aya-expanse-32b", "endpoints": ["chat"]}]})

    m = _model(handler)
    assert m.list_models() == ["c4ai-aya-expanse-32b", "command-a-03-2025"]
    assert m.check() == {"ok": True, "models": ["c4ai-aya-expanse-32b", "command-a-03-2025"],
                         "has_model": True}


def test_check_explains_rejected_key():
    def handler(req):
        return httpx.Response(401, json={"message": "invalid api token"})

    r = _model(handler).check()
    assert not r["ok"] and "rejected the API key" in r["error"]


def test_with_model_and_build_model_wiring():
    m = _model(lambda req: httpx.Response(200, json={}))
    assert m.with_model("x").name == "cohere:x" and m.with_model("x").api_key == "k"
    s = Settings(provider="cohere", model="command-a-03-2025", api_key="k",
                 endpoint="http://127.0.0.1:11434/v1")
    built = build_model(s)
    assert isinstance(built, CohereModel) and built.endpoint == "https://api.cohere.com"
