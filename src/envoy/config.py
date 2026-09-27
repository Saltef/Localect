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
    memory_capture: bool = True  # False pauses capture: POST /api/messages stores nothing
    # The browser extension proves it is yours with this token (Authorization: Bearer).
    # Generated on first start; shown in Settings; never sent anywhere else.
    extension_token: str = ""
    # Hosting. owner_password_hash: set with `envoy config --owner-password`; when set,
    # the web UI and API need a login (the extension token also counts). public_mode:
    # "off" (default) or "demo": visitors get Compose on the demo store, isolated from
    # the owner's data, capped per IP per hour and per day, on public_model ("stub" or
    # "configured": the owner's model and key). trust_proxy: honour X-Forwarded-* from
    # the reverse proxy in front.
    owner_password_hash: str = ""
    public_mode: str = "off"
    public_model: str = "stub"
    public_hourly: int = 20
    public_daily: int = 300
    trust_proxy: bool = False
    # Experiment switches (see docs/EVAL.md, "The experiment"): no_critic,
    # no_rewriter, no_revision, no_voice, facts_only, no_facts. Off in normal use.
    ablations: list[str] = field(default_factory=list)

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
        if env.get("ENVOY_OWNER_PASSWORD"):
            from .auth import hash_password

            s.owner_password_hash = hash_password(env["ENVOY_OWNER_PASSWORD"])
        s.public_mode = env.get("ENVOY_PUBLIC_MODE", s.public_mode)
        if env.get("ENVOY_ABLATIONS") is not None:
            s.ablations = [a.strip() for a in env["ENVOY_ABLATIONS"].split(",") if a.strip()]
        s.public_model = env.get("ENVOY_PUBLIC_MODEL", s.public_model)
        s.public_hourly = int(env.get("ENVOY_PUBLIC_HOURLY", s.public_hourly))
        s.public_daily = int(env.get("ENVOY_PUBLIC_DAILY", s.public_daily))
        s.trust_proxy = env.get("ENVOY_TRUST_PROXY", str(s.trust_proxy)).lower() in ("1", "true")
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
        d["extension_token"] = "set" if self.extension_token else ""
        d["owner_password_hash"] = "set" if self.owner_password_hash else ""
        return d

    @property
    def auth_required(self) -> bool:
        return bool(self.owner_password_hash)

    def ensure_extension_token(self) -> str:
        if not self.extension_token:
            import secrets

            self.extension_token = secrets.token_urlsafe(24)
            self.save()
        return self.extension_token
