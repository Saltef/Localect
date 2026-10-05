"""Embedders behind one interface, so retrieval works across languages.

- ``HashEmbedder``: offline and deterministic. Hashed bag of words and
  character n-grams, with Localect's cross-lingual alias table folded in, so
  "devolução", "return" and "استرداد" share a dimension. Used by the stub, in
  CI, and as the fallback when no model is configured.
- ``OpenAICompatEmbedder``: any server with ``/embeddings`` (Ollama, LM Studio,
  vLLM) and a multilingual model such as bge-m3 or nomic-embed-text.
- ``CohereEmbedder``: Cohere's ``/v2/embed`` with embed-multilingual-v3.0.

Vectors are unit length, stored as float32 bytes; similarity is a dot product.
"""

from __future__ import annotations

import math
import re
import zlib
from array import array
from typing import Any, Protocol

import httpx

from ..config import Settings
from ..models.base import ModelError
from ..models.openai_compat import _retry
from ..text import tokens

QUERY, DOCUMENT = "query", "document"


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str], kind: str = DOCUMENT) -> list[list[float]]: ...


def to_bytes(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def from_bytes(raw: bytes) -> array:
    a = array("f")
    a.frombytes(raw)
    return a


def normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else vec


def dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


class HashEmbedder:
    name = "hash-v1"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _bucket(self, feat: str) -> tuple[int, float]:
        h = zlib.crc32(feat.encode("utf-8"))
        return h % self.dim, 1.0 if (h >> 31) & 1 else -1.0

    def _features(self, text: str) -> dict[str, float]:
        feats: dict[str, float] = {}
        # Canonical tokens: the alias table maps translations of the same
        # concept to one key, which is what makes this cross-lingual.
        for t in tokens(text):
            feats[f"w:{t}"] = feats.get(f"w:{t}", 0.0) + 2.0
        for raw in re.findall(r"\w+", text.lower()):
            padded = f"<{raw}>"
            if len(padded) < 4:
                continue
            for i in range(len(padded) - 2):
                g = padded[i:i + 3]
                feats[f"c:{g}"] = feats.get(f"c:{g}", 0.0) + 0.5
        return feats

    def embed(self, texts: list[str], kind: str = DOCUMENT) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for feat, weight in self._features(text).items():
                i, sign = self._bucket(feat)
                vec[i] += sign * weight
            out.append(normalize(vec))
        return out


class OpenAICompatEmbedder:
    def __init__(self, endpoint: str, model: str, api_key: str = "", timeout: float = 120.0):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = f"openai:{model}"
        self.dim = 0
        self._client = httpx.Client(timeout=timeout)

    def embed(self, texts: list[str], kind: str = DOCUMENT) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        def go():
            r = self._client.post(f"{self.endpoint}/embeddings",
                                  json={"model": self.model, "input": texts}, headers=headers)
            r.raise_for_status()
            return r.json()

        try:
            body = _retry(go)
            rows = sorted(body["data"], key=lambda d: d.get("index", 0))
            vecs = [normalize([float(x) for x in d["embedding"]]) for d in rows]
        except httpx.HTTPStatusError as e:
            raise ModelError(f"embeddings: {e.response.status_code}: "
                             f"{e.response.text[:200]}") from e
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
            raise ModelError(f"embeddings request failed: {e}") from e
        if vecs:
            self.dim = len(vecs[0])
        return vecs


class CohereEmbedder:
    def __init__(self, api_key: str, model: str = "embed-multilingual-v3.0",
                 endpoint: str = "https://api.cohere.com", timeout: float = 120.0):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = f"cohere:{model}"
        self.dim = 0
        self._client = httpx.Client(timeout=timeout)

    def embed(self, texts: list[str], kind: str = DOCUMENT) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        input_type = "search_query" if kind == QUERY else "search_document"
        vecs: list[list[float]] = []
        for i in range(0, len(texts), 96):  # Cohere's batch limit
            batch = texts[i:i + 96]

            def go(batch=batch):
                r = self._client.post(f"{self.endpoint}/v2/embed", headers=headers, json={
                    "model": self.model, "texts": batch, "input_type": input_type,
                    "embedding_types": ["float"]})
                r.raise_for_status()
                return r.json()

            try:
                body = _retry(go)
                vecs += [normalize([float(x) for x in v]) for v in body["embeddings"]["float"]]
            except httpx.HTTPStatusError as e:
                raise ModelError(f"Cohere embed returned {e.response.status_code}: "
                                 f"{e.response.text[:200]}") from e
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
                raise ModelError(f"embeddings request failed: {e}") from e
        if vecs:
            self.dim = len(vecs[0])
        return vecs


def build_embedder(settings: Settings) -> Embedder:
    """The embedder the settings imply. Cohere gets its multilingual model by
    default; an OpenAI-compatible server is used only when ``embed_model`` names
    one it serves; everything else is the offline hashed embedder."""
    if settings.provider == "cohere" and settings.api_key:
        return CohereEmbedder(settings.api_key, settings.embed_model or "embed-multilingual-v3.0")
    if settings.provider == "openai" and settings.embed_model:
        return OpenAICompatEmbedder(settings.endpoint, settings.embed_model, settings.api_key)
    return HashEmbedder()


def describe(embedder: Embedder) -> dict[str, Any]:
    return {"name": embedder.name, "offline": isinstance(embedder, HashEmbedder)}
