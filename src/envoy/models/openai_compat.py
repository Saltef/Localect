"""Any local or hosted server speaking the OpenAI chat-completions API.

Ollama, LM Studio, llama.cpp server, and vLLM all do. This is the default
path for real models; the user sets an endpoint and a model name.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel

from .base import Message, ModelError


class OpenAICompatModel:
    def __init__(self, endpoint: str, model: str, api_key: str = "", timeout: float = 180.0):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = f"openai:{model}"
        self._client = httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = self._client.post(
            f"{self.endpoint}/chat/completions", json=payload, headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

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
            payload["response_format"] = {"type": "json_object"}
        try:
            try:
                body = self._post(payload)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400 and "response_format" in payload:
                    payload.pop("response_format")
                    body = self._post(payload)
                else:
                    raise
        except httpx.HTTPError as e:
            raise ModelError(f"model request failed: {e}") from e
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError(f"unexpected response shape: {body!r}"[:300]) from e

    def with_model(self, model: str) -> OpenAICompatModel:
        """Same endpoint and key, a different model name."""
        other = OpenAICompatModel.__new__(OpenAICompatModel)
        other.endpoint, other.api_key, other._client = self.endpoint, self.api_key, self._client
        other.model, other.name = model, f"openai:{model}"
        return other

    def list_models(self) -> list[str]:
        r = self._client.get(f"{self.endpoint}/models", headers=self._headers())
        r.raise_for_status()
        data = r.json().get("data", [])
        return sorted(m.get("id") for m in data if m.get("id"))

    def check(self) -> dict[str, Any]:
        """Is the endpoint reachable and can it serve our model?

        Tries the model list first. Endpoints that do not expose one fall back
        to a one-token chat call with the configured model.
        """
        try:
            names = self.list_models()
            return {"ok": True, "models": names, "has_model": self.model in names}
        except httpx.HTTPError as list_err:
            try:
                self._post({"model": self.model, "max_tokens": 1,
                            "messages": [{"role": "user", "content": "ping"}]})
                return {"ok": True, "models": [], "has_model": True,
                        "note": "this endpoint does not list models; the configured "
                                "model answered"}
            except httpx.HTTPError as e:
                return {"ok": False, "error": f"{e} (model list: {list_err})",
                        "models": [], "has_model": False}
