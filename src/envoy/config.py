"""Settings: environment variables first, then a JSON file in the data dir.

Nothing is required. With no configuration at all Envoy runs on the stub
adapter against a data directory under the user's home.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"


def data_dir() -> Path:
    d = Path(os.environ.get("ENVOY_DATA_DIR", Path.home() / ".envoy"))
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Settings:
    provider: str = "stub"  # stub | openai | cohere
    endpoint: str = DEFAULT_ENDPOINT
    model: str = "aya-expanse:8b"
    api_key: str = ""  # only for hosted OpenAI-compatible endpoints
    user_name: str = ""
    user_email: str = ""  # marks which imported or captured messages you wrote (comma-separated)
    user_language: str = "en"
    host: str = "127.0.0.1"
    port: int = 8765
    role_models: dict[str, str] = field(default_factory=dict)  # per-agent overrides
    # Embedding model for memory search: "" picks the provider's default (Cohere:
    # embed-multilingual-v3.0; otherwise the offline hashed embedder). For an
    # OpenAI-compatible server, name a model it serves (e.g. bge-m3, nomic-embed-text).
    embed_model: str = ""

    @property
    def db_path(self) -> Path:
        return data_dir() / "envoy.db"

    @classmethod
    def load(cls) -> Settings:
        s = cls()
        f = data_dir() / "settings.json"
        if f.exists():
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except json.JSONDecodeError:
                pass
        env = os.environ
        s.provider = env.get("ENVOY_PROVIDER", s.provider)
        s.endpoint = env.get("ENVOY_ENDPOINT", s.endpoint)
        s.model = env.get("ENVOY_MODEL", s.model)
        s.api_key = env.get("ENVOY_API_KEY", s.api_key)
        s.user_language = env.get("ENVOY_USER_LANGUAGE", s.user_language)
        s.user_email = env.get("ENVOY_USER_EMAIL", s.user_email)
        s.embed_model = env.get("ENVOY_EMBED_MODEL", s.embed_model)
        s.host = env.get("ENVOY_HOST", s.host)
        s.port = int(env.get("ENVOY_PORT", s.port))
        return s

    @property
    def my_addresses(self) -> set[str]:
        return {a.strip().lower() for a in self.user_email.split(",") if a.strip()}

    def save(self) -> None:
        f = data_dir() / "settings.json"
        f.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    def public(self) -> dict:
        d = asdict(self)
        d["api_key"] = "set" if self.api_key else ""
        return d
