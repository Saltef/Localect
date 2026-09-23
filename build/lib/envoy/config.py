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
    provider: str = "stub"  # stub | openai
    endpoint: str = DEFAULT_ENDPOINT
    model: str = "aya-expanse:8b"
    api_key: str = ""  # only for hosted OpenAI-compatible endpoints
    user_name: str = ""
    user_language: str = "en"
    host: str = "127.0.0.1"
    port: int = 8765
    role_models: dict[str, str] = field(default_factory=dict)  # per-agent overrides

    @property
    def db_path(self) -> Path:
        return data_dir() / "envoy.db"

    @classmethod
    def load(cls) -> Settings:
        s = cls()
        f = data_dir() / "settings.json"
        if f.exists():
            try:
                raw = json.loads(f.read_text())
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
        s.host = env.get("ENVOY_HOST", s.host)
        s.port = int(env.get("ENVOY_PORT", s.port))
        return s

    def save(self) -> None:
        f = data_dir() / "settings.json"
        f.write_text(json.dumps(asdict(self), indent=2))

    def public(self) -> dict:
        d = asdict(self)
        d["api_key"] = "set" if self.api_key else ""
        return d
