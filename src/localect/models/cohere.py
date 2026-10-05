"""Cohere's native API (v2 chat), called directly with an API key.

No OpenAI compatibility layer in between: the request and response shapes are
Cohere's own, and the model list comes from Cohere's models endpoint.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel

from .base import Message, ModelError


def _retry(fn, attempts: int = 3, base_delay: float = 1.0):
    """Retry a request on 429 and 5xx, honouring Retry-After when present."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code != 429 and code < 500:
                raise
            last = e
            wait = base_delay * (2 ** i)
            ra = e.response.headers.get("retry-after")
            if ra and ra.isdigit():
                wait = max(wait, float(ra))
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last = e
            wait = base_delay * (2 ** i)
        if i < attempts - 1:
            time.sleep(min(wait, 10.0))
    assert last is not None
    raise last

DEFAULT_ENDPOINT = "https://api.cohere.com"


class CohereModel:
    def __init__(self, model: str, api_key: str, endpoint: str = DEFAULT_ENDPOINT,
                 timeout: float = 180.0):
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = f"cohere:{model}"
        self._client = httpx.Client(timeout=timeout)
        # Whether this model accepts a JSON schema in response_format; learned on
        # the first 400 so a model that rejects it is not asked twice per call.
        self._schema_ok: bool | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                "Accept": "application/json"}

    def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        def go():
            r = self._client.post(f"{self.endpoint}/v2/chat", json=payload,
                                  headers=self._headers())
            r.raise_for_status()
            return r.json()

        return _retry(go)

    def with_model(self, model: str) -> CohereModel:
        other = CohereModel.__new__(CohereModel)
        other.endpoint, other.api_key, other._client = self.endpoint, self.api_key, self._client
        other.model, other.name = model, f"cohere:{model}"
        other._schema_ok = None
        return other

    def list_models(self) -> list[str]:
        r = self._client.get(f"{self.endpoint}/v1/models",
                             params={"page_size": 100, "endpoint": "chat"},
                             headers=self._headers())
        r.raise_for_status()
        out = []
        for m in r.json().get("models", []):
            name = m.get("name")
            endpoints = m.get("endpoints") or ["chat"]
            if name and "chat" in endpoints:
                out.append(name)
        return sorted(out)

    def generate(
        self,
        messages: list[Message],
        *,
        role: str,
        schema: type[BaseModel] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0}
        if schema is not None:
            payload["response_format"] = self._response_format(schema)
        try:
            try:
                body = self._chat(payload)
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 400 or "response_format" not in payload:
                    raise
                if "json_schema" in payload["response_format"]:
                    # The schema was refused: constrain to JSON only, and remember.
                    self._schema_ok = False
                    payload["response_format"] = {"type": "json_object"}
                    try:
                        body = self._chat(payload)
                    except httpx.HTTPStatusError as e2:
                        if e2.response.status_code != 400:
                            raise
                        payload.pop("response_format")
                        body = self._chat(payload)
                else:
                    payload.pop("response_format")
                    body = self._chat(payload)
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:200]
            raise ModelError(f"Cohere returned {e.response.status_code}: {detail}") from e
        except httpx.HTTPError as e:
            raise ModelError(f"model request failed: {e}") from e
        try:
            parts = body["message"]["content"]
            return "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise ModelError(f"unexpected response shape: {body!r}"[:300]) from e

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any]:
        """Structured output: the schema itself when the model accepts one, so
        it cannot echo the schema or drop a required key; JSON mode otherwise."""
        if self._schema_ok is False:
            return {"type": "json_object"}
        return {"type": "json_object", "json_schema": schema.model_json_schema()}

    def check(self) -> dict[str, Any]:
        try:
            names = self.list_models()
            return {"ok": True, "models": names, "has_model": self.model in names}
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                return {"ok": False, "error": "Cohere rejected the API key (HTTP "
                        f"{e.response.status_code})", "models": [], "has_model": False}
            list_err = e
        except httpx.HTTPError as e:
            list_err = e
        try:
            self._chat({"model": self.model, "max_tokens": 1,
                        "messages": [{"role": "user", "content": "ping"}]})
            return {"ok": True, "models": [], "has_model": True,
                    "note": "model list unavailable; the configured model answered"}
        except httpx.HTTPError as e:
            return {"ok": False, "error": f"{e} (model list: {list_err})", "models": [],
                    "has_model": False}
