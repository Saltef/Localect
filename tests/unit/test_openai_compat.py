import httpx

from envoy.models.openai_compat import OpenAICompatModel


def _model(handler):
    m = OpenAICompatModel("http://x/v1", "m1", "k")
    m._client = httpx.Client(transport=httpx.MockTransport(handler))
    return m


def test_check_lists_models_and_sends_bearer():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"id": "m2"}, {"id": "m1"}]})

    r = _model(handler).check()
    assert r == {"ok": True, "models": ["m1", "m2"], "has_model": True}
    assert seen["auth"] == "Bearer k"


def test_check_falls_back_to_chat_ping_when_models_unlisted():
    def handler(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(404)
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    r = _model(handler).check()
    assert r["ok"] and r["has_model"] and r["models"] == [] and "does not list" in r["note"]


def test_check_reports_unreachable():
    def handler(req):
        raise httpx.ConnectError("refused")

    r = _model(handler).check()
    assert not r["ok"] and "refused" in r["error"]


def test_generate_retries_without_response_format_on_400():
    calls = []

    def handler(req):
        body = req.read().decode()
        calls.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": "unsupported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    from pydantic import BaseModel

    class S(BaseModel):
        pass

    out = _model(handler).generate([{"role": "user", "content": "x"}], role="reader", schema=S)
    assert out == "{}" and calls == [True, False]


def test_with_model_shares_endpoint_and_key():
    m = _model(lambda req: httpx.Response(200, json={}))
    other = m.with_model("m9")
    assert other.model == "m9" and other.name == "openai:m9"
    assert other.endpoint == m.endpoint and other.api_key == m.api_key
