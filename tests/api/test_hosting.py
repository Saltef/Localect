"""Owner login, the public demo, and their isolation."""

from fastapi.testclient import TestClient

from localect import auth, db
from localect.app import create_app
from localect.config import Settings
from localect.locales import seed_locales


def _client(monkeypatch, tmp_path, **kw):
    monkeypatch.setenv("LOCALECT_DATA_DIR", str(tmp_path))
    con = db.connect()
    seed_locales(con)
    s = Settings(provider="stub", user_name="Safea", user_email="safea@example.com", **kw)
    app = create_app(settings=s, con=con, use_mcp=False)
    return TestClient(app), con


def test_no_password_means_no_login(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path)[0] as c:
        h = c.get("/api/health").json()
        assert h["auth_required"] is False and h["owner"] is True
        assert c.post("/api/login", json={"password": "anything"}).json()["owner"]


def test_password_gates_everything_and_the_session_cookie_opens_it(monkeypatch, tmp_path):
    pw = auth.hash_password("hunter2-but-longer")
    with _client(monkeypatch, tmp_path, owner_password_hash=pw)[0] as c:
        h = c.get("/api/health").json()
        assert (h["auth_required"], h["owner"], h["model"]) == (True, False, "")
        for path in ("/api/settings", "/api/messages", "/api/glossary", "/api/extension/token"):
            assert c.get(path).status_code == 401, path
        assert c.post("/api/compose", json={"message": "hi"}).status_code == 401
        assert c.post("/api/login", json={"password": "nope"}).status_code == 401
        r = c.post("/api/login", json={"password": "hunter2-but-longer"})
        assert r.status_code == 200 and auth.COOKIE in r.cookies
        assert c.get("/api/health").json()["owner"] is True
        assert c.get("/api/settings").json()["owner_password_hash"] == "set"
        assert c.post("/api/compose", json={"message": "Hi, when does it ship?"}).status_code \
            == 200
        assert c.post("/api/logout").status_code == 200
        assert c.get("/api/health").json()["owner"] is False
        # the extension's token is the owner too
        token = Settings.load() and c.app.state.settings.ensure_extension_token()
        r = c.get("/api/memory", headers={"Origin": "chrome-extension://abc",
                                          "Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        # settings cannot be used to change the password hash
        c.post("/api/login", json={"password": "hunter2-but-longer"})
        c.put("/api/settings", json={"owner_password_hash": ""})
        c.post("/api/logout")
        assert c.get("/api/settings").status_code == 401


def test_login_attempts_are_capped(monkeypatch, tmp_path):
    pw = auth.hash_password("secret-enough")
    with _client(monkeypatch, tmp_path, owner_password_hash=pw, public_hourly=2)[0] as c:
        assert c.post("/api/login", json={"password": "a"}).status_code == 401
        assert c.post("/api/login", json={"password": "b"}).status_code == 401
        assert c.post("/api/login", json={"password": "secret-enough"}).status_code == 429


def test_public_demo_is_isolated_capped_and_forgets(monkeypatch, tmp_path):
    pw = auth.hash_password("owner-pass-word")
    c, con = _client(monkeypatch, tmp_path, owner_password_hash=pw, public_mode="demo",
                     public_hourly=2, public_daily=10)
    with c:
        # the owner's private memory holds a fact a visitor must never see
        db.message_add(con, text="Our secret return window is 99 days.", is_mine=True,
                       from_addr="safea@example.com", date="2026-01-01T00:00:00Z", language="en")
        con.commit()
        h = c.get("/api/health").json()
        assert h["owner"] is False and h["public_mode"] == "demo" and h["tries_left"] == 2
        assert h["provider"] == "stub"
        # visitors may compose on the demo store, not read anything else
        assert c.get("/api/settings").status_code == 401
        assert c.get("/api/messages").status_code == 401
        assert c.get("/api/demo/messages").status_code == 200
        r = c.post("/api/compose", json={"message": "Hi, how long is the return window?"})
        assert r.status_code == 200
        text = r.json()["result"]["final_text"]
        assert "30" in text and "99" not in text, "the demo store answers, the owner's mail never"
        assert all(s["kind"] != "mail" for s in r.json()["result"]["sources"])
        assert c.get("/api/health").json()["tries_left"] == 1
        # nothing kept: the owner's history has no visitor replies
        c.post("/api/login", json={"password": "owner-pass-word"})
        assert c.get("/api/history").json() == []
        c.post("/api/logout")
        # the cap
        assert c.post("/api/compose", json={"message": "again?"}).status_code == 200
        assert c.post("/api/compose", json={"message": "and again?"}).status_code == 429
        assert c.post("/api/compose", json={"message": "x" * 20001}).status_code in (413, 429)


def test_proxy_headers_drive_the_client_address_and_origin_check(monkeypatch, tmp_path):
    pw = auth.hash_password("owner-pass-word")
    c, _ = _client(monkeypatch, tmp_path, owner_password_hash=pw, public_mode="demo",
                   public_hourly=1, trust_proxy=True)
    with c:
        a = {"X-Forwarded-For": "203.0.113.1, 10.0.0.2"}
        b = {"X-Forwarded-For": "203.0.113.2"}
        assert c.post("/api/compose", json={"message": "hi there"}, headers=a).status_code == 200
        assert c.post("/api/compose", json={"message": "hi there"}, headers=a).status_code == 429
        assert c.post("/api/compose", json={"message": "hi there"}, headers=b).status_code == 200
        # the app's own page behind an HTTPS proxy: Origin is https, host matches
        r = c.post("/api/login", json={"password": "owner-pass-word"},
                   headers={"Origin": "https://testserver", "X-Forwarded-Proto": "https"})
        assert r.status_code == 200 and "Secure" in r.headers.get("set-cookie", "")
        assert c.post("/api/login", json={"password": "owner-pass-word"},
                      headers={"Origin": "https://evil.example"}).status_code == 403
