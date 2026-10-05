"""Owner login and visitor limits for a hosted Localect.

On a laptop nothing here is active: no password, no public mode, every
request is the owner's. Hosted, the owner sets a password (hashed with
PBKDF2, never stored in clear) and signs in once; a signed, expiring cookie
carries the session. The browser extension's pairing token also counts as
the owner. Visitors exist only when public mode is on, and then only for the
demo: a separate in-memory database seeded with the demo store, no history,
a per-IP hourly cap and a daily cap, and a model of the owner's choosing
(the stub by default, so a stranger can never spend the owner's key unless
the owner says so)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

PBKDF2_ROUNDS = 200_000
SESSION_DAYS = 30
COOKIE = "localect_session"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, digest = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return hmac.compare_digest(candidate, digest)


def server_secret(data_dir: Path) -> bytes:
    """A random key for signing sessions, created once per data directory."""
    f = data_dir / "secret.key"
    if not f.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        f.write_bytes(secrets.token_bytes(32))
        try:
            f.chmod(0o600)
        except OSError:
            pass
    return f.read_bytes()


def issue_session(secret: bytes, days: int = SESSION_DAYS) -> str:
    expires = str(int(time.time()) + days * 86400)
    sig = hmac.new(secret, expires.encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def session_valid(secret: bytes, value: str | None) -> bool:
    if not value or "." not in value:
        return False
    expires, sig = value.rsplit(".", 1)
    good = hmac.new(secret, expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, sig) and expires.isdigit() and int(expires) > time.time()


class RateLimit:
    """Sliding-window counters: per key per hour, and one for everyone per day."""

    def __init__(self, per_hour: int, per_day: int) -> None:
        self.per_hour, self.per_day = per_hour, per_day
        self._hourly: dict[str, deque[float]] = defaultdict(deque)
        self._daily: deque[float] = deque()

    def _prune(self, q: deque[float], window: float, now: float) -> None:
        while q and q[0] < now - window:
            q.popleft()

    def remaining(self, key: str, now: float | None = None) -> tuple[int, int]:
        now = now or time.time()
        self._prune(self._hourly[key], 3600, now)
        self._prune(self._daily, 86400, now)
        return (max(0, self.per_hour - len(self._hourly[key])),
                max(0, self.per_day - len(self._daily)))

    def take(self, key: str, now: float | None = None) -> bool:
        now = now or time.time()
        h, d = self.remaining(key, now)
        if h <= 0 or d <= 0:
            return False
        self._hourly[key].append(now)
        self._daily.append(now)
        return True
