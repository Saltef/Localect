import time

from localect import auth


def test_password_hashing_is_salted_and_verifies():
    h1, h2 = auth.hash_password("correct horse"), auth.hash_password("correct horse")
    assert h1 != h2 and h1.startswith("pbkdf2$")
    assert auth.check_password("correct horse", h1) and auth.check_password("correct horse", h2)
    assert not auth.check_password("wrong", h1) and not auth.check_password("x", "garbage")


def test_sessions_are_signed_and_expire(tmp_path):
    secret = auth.server_secret(tmp_path)
    assert secret == auth.server_secret(tmp_path) and len(secret) == 32
    token = auth.issue_session(secret)
    assert auth.session_valid(secret, token)
    assert not auth.session_valid(auth.server_secret(tmp_path / "other"), token)
    expires, sig = token.rsplit(".", 1)
    assert not auth.session_valid(secret, f"{int(expires) + 1}.{sig}")  # tampered
    assert not auth.session_valid(secret, "") and not auth.session_valid(secret, None)
    old = auth.issue_session(secret, days=0)
    time.sleep(0.01)
    assert not auth.session_valid(secret, old.replace(old.split(".")[0], str(int(time.time()) - 1)))


def test_rate_limit_per_key_per_hour_and_global_per_day():
    rl = auth.RateLimit(per_hour=2, per_day=3)
    t = 1_000_000.0
    assert rl.take("a", t) and rl.take("a", t + 1) and not rl.take("a", t + 2)
    assert rl.remaining("a", t + 2) == (0, 1)
    assert rl.take("b", t + 3) and not rl.take("b", t + 4)  # daily cap reached
    assert rl.remaining("c", t + 5) == (2, 0)
    assert rl.take("a", t + 3601)  is False  # hour passed for "a", but the day has not
    assert rl.take("a", t + 86401) is True
