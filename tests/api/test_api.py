from fastapi.testclient import TestClient

from localect import db
from localect.app import create_app
from localect.locales import seed_locales


def _client(settings):
    con = db.connect()
    seed_locales(con)
    app = create_app(settings=settings, con=con, use_mcp=False)
    return TestClient(app), con


def test_health_and_settings(settings):
    with _client(settings)[0] as c:
        h = c.get("/api/health").json()
        assert h["ok"] and h["provider"] == "stub" and h["mcp"] is False
        assert c.get("/api/settings").json()["user_name"] == "Safea"
        assert c.get("/api/settings/check").json()["ok"]


def test_demo_then_compose_full_result(settings):
    with _client(settings)[0] as c:
        assert c.post("/api/demo").json()["knowledge"] == 5
        assert c.post("/api/demo").json()["knowledge"] == 0  # idempotent
        msgs = c.get("/api/demo/messages").json()
        r = c.post("/api/compose", json={"message": msgs[0]["text"]})
        assert r.status_code == 200
        res = r.json()["result"]
        assert res["locale"]["locale"] == "ar-LB" and res["status"] == "ready"
        assert res["back_translation"] and res["ledger"][1]["source_ids"]
        assert c.get("/api/history").json()[0]["id"] == res["id"]
        assert c.get(f"/api/history/{res['id']}").json()["final_text"] == res["final_text"]


def test_empty_message_is_400(settings):
    with _client(settings)[0] as c:
        assert c.post("/api/compose", json={"message": "   "}).status_code == 400


def test_glossary_contacts_knowledge_crud(settings):
    with _client(settings)[0] as c:
        gid = c.post("/api/glossary",
                     json={"term": "SkyPack", "do_not_translate": True}).json()["id"]
        assert c.get("/api/glossary").json()[0]["term"] == "SkyPack"
        assert c.delete(f"/api/glossary/{gid}").json()["ok"] and c.get("/api/glossary").json() == []
        cid = c.post("/api/contacts", json={"name": "Layla", "locale": "ar-LB"}).json()["id"]
        assert c.get("/api/contacts").json()[0]["id"] == cid
        kid = c.post("/api/knowledge",
                     json={"title": "T", "text": "Orders ship fast."}).json()["id"]
        assert c.get("/api/knowledge").json()[0]["id"] == kid
        assert c.delete(f"/api/knowledge/{kid}").json()["ok"]


def test_locales_get_and_put(settings):
    with _client(settings)[0] as c:
        ps = c.get("/api/locales").json()
        assert len(ps) == 12
        p = c.get("/api/locales/ar-EG").json()
        p["greeting"] = "يا {name}،"
        assert c.put("/api/locales/ar-EG", json=p).json()["greeting"] == "يا {name}،"
        assert c.get("/api/locales/xx-XX").status_code == 404


def test_put_settings_rebuilds_model(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALECT_DATA_DIR", str(tmp_path))
    with _client(settings)[0] as c:
        out = c.put("/api/settings", json={"user_name": "Nadir", "api_key": "k"}).json()
        assert out["user_name"] == "Nadir" and out["api_key"] == "set"
        assert (tmp_path / "settings.json").exists()


def test_models_endpoint_and_override_on_stub(settings):
    with _client(settings)[0] as c:
        r = c.get("/api/models").json()
        assert r["models"] == [] and r["current"] == "stub"
        c.post("/api/demo")
        out = c.post("/api/compose", json={"message": "When does order #1 ship?",
                                           "model": "anything"}).json()
        assert out["result"]["model"] == "stub"  # override is ignored without a real endpoint


def test_messages_import_capture_and_delete(settings, tmp_path):
    from pathlib import Path

    fix = Path(__file__).resolve().parents[1] / "fixtures" / "mail"
    settings.user_email = "safea@example.com"
    with _client(settings)[0] as c:
        assert c.post("/api/import", json={"paths": [str(tmp_path / "nope")]}).status_code == 400
        r = c.post("/api/import", json={"paths": [str(fix / "warranty.eml")]}).json()
        assert r["messages"] == 1 and r["mine"] == 1 and r["counts"]["messages"] == 1
        assert r["indexed"]["mail"] >= 1
        mem = c.get("/api/memory").json()
        assert mem["embedder"] == {"name": "hash-v1", "offline": True}
        assert mem["vectors"]["mail:hash-v1"] >= 1
        # a captured message: quotes stripped, "mine" decided from settings.user_email
        cap = c.post("/api/messages", json={
            "text": "Sure, 30 days.\n\nOn Mon, Jo wrote:\n> how long?",
            "from_addr": "Safea@example.com", "to_addrs": ["jo@partner.example"],
            "subject": "Re: window"}).json()
        assert cap["stored"]
        m = c.get(f"/api/messages/{cap['id']}").json()
        assert m["text"] == "Sure, 30 days." and m["is_mine"] == 1 and m["origin"] == "capture"
        assert m["date"] and m["to_addrs"] == "jo@partner.example"
        assert c.post("/api/index").json()["indexed"] == {"mail": 0, "knowledge": 0}  # captured
        assert c.post("/api/messages", json={"text": "> only a quote"}).status_code == 400
        listing = c.get("/api/messages", params={"q": "window"}).json()
        assert listing["counts"]["messages"] == 2 and len(listing["messages"]) == 1
        assert c.delete(f"/api/messages/{cap['id']}").json()["ok"]
        assert c.get("/api/messages").json()["counts"]["messages"] == 1
        # settings accept the address and mask nothing else
        assert c.put("/api/settings", json={"user_email": "me@x.example"}).json()["user_email"] \
            == "me@x.example"


def test_facts_extract_review_and_memory_status(settings):
    from pathlib import Path

    fix = Path(__file__).resolve().parents[1] / "fixtures" / "mail"
    settings.user_email = "safea@example.com"
    with _client(settings)[0] as c:
        c.post("/api/import", json={"paths": [str(fix / "sample.mbox")]})
        mem = c.get("/api/memory").json()
        assert mem["unextracted"] == 5 and mem["facts"]["facts"] == 0
        ex = c.post("/api/extract").json()
        assert ex["messages"] == 5 and ex["facts_total"]["facts"] >= 2
        mem = c.get("/api/memory").json()
        assert mem["unextracted"] == 0 and len(mem["conflicts"]) == 1
        facts = c.get("/api/facts", params={"q": "return window"}).json()
        assert [f["value"] for f in facts] == ["30", "14"]
        assert c.get("/api/facts", params={"party": "layla@shop.example"}).json()
        assert c.put(f"/api/facts/{facts[1]['id']}", json={"status": "banana"}).status_code == 400
        assert c.put(f"/api/facts/{facts[1]['id']}", json={"status": "rejected"}).json()["status"] \
            == "rejected"
        assert c.get("/api/memory").json()["conflicts"] == []
        fixed = c.put(f"/api/facts/{facts[0]['id']}", json={"topic": "Return period",
                                                             "value": "30 days"}).json()
        assert fixed["topic"] == "Return period" and fixed["topic_key"] == "period return"
        assert c.put("/api/facts/nope", json={"status": "confirmed"}).status_code == 404
        assert c.delete(f"/api/facts/{facts[0]['id']}").json()["ok"]
        # a captured message is read for facts on arrival
        cap = c.post("/api/messages", json={"text": "Shipping to Cairo takes 4 days.",
                                            "from_addr": "safea@example.com",
                                            "to_addrs": ["omar@example.org"]}).json()
        assert cap["stored"] and cap["facts"] == 1
        assert c.get("/api/facts", params={"q": "cairo"}).json()[0]["value"] == "4"


def test_exclusions_and_capture_pause(settings):
    from pathlib import Path

    fix = Path(__file__).resolve().parents[1] / "fixtures" / "mail"
    settings.user_email = "safea@example.com"
    with _client(settings)[0] as c:
        c.post("/api/import", json={"paths": [str(fix / "sample.mbox")]})
        c.post("/api/extract")
        m = c.get("/api/messages").json()["messages"][-1]  # oldest: the return window thread
        detail = c.get(f"/api/messages/{m['id']}").json()
        assert detail["text"].startswith("Hi Layla") and detail["facts"][0]["value"] == "14"
        assert c.post("/api/exclusions", json={"kind": "banana", "value": "x"}).status_code == 400
        x = c.post("/api/exclusions", json={"kind": "thread", "value": m["thread_id"]}).json()
        assert x["counts"]["excluded"] == 2
        assert c.get("/api/exclusions").json()[0]["messages"] == 2
        mem = c.get("/api/memory").json()
        assert mem["exclusions"] == 1 and mem["capture"] is True and mem["conflicts"] == []
        assert c.delete(f"/api/exclusions/{x['id']}").json()["counts"]["excluded"] == 0
        # pausing capture: nothing stored, nothing raised, and the state is visible
        assert c.put("/api/settings", json={"memory_capture": False}).json()["memory_capture"] \
            is False
        r = c.post("/api/messages", json={"text": "Paused note.", "from_addr": "x@y"}).json()
        assert r == {"id": None, "stored": False, "facts": 0, "reason": "capture is paused"}
        assert c.get("/api/memory").json()["capture"] is False
        c.put("/api/settings", json={"memory_capture": True})
        assert c.post("/api/messages", json={"text": "Live again.", "from_addr": "x@y"}).json()[
            "stored"]


def test_origin_guard_and_extension_pairing(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALECT_DATA_DIR", str(tmp_path))
    with _client(settings)[0] as c:
        # no Origin (CLI, curl, tests): unaffected
        assert c.get("/api/health").status_code == 200
        # the app's own page
        own = {"Origin": "http://testserver"}
        assert c.get("/api/health", headers=own).status_code == 200
        # a random web page reaching localhost: refused
        r = c.post("/api/messages", json={"text": "x"}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        # an extension without the token: told to pair; with it: allowed, CORS headers present
        ext = {"Origin": "chrome-extension://abcdefghijklmnop"}
        assert c.get("/api/extension/status", headers=ext).status_code == 401
        token = c.get("/api/extension/token", headers=own).json()["token"]
        assert len(token) >= 30 and c.get("/api/settings").json()["extension_token"] == "set"
        r = c.get("/api/extension/status", headers={**ext, "Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.json()["capture"] is True
        assert r.headers.get("access-control-allow-origin") == ext["Origin"]
        # the extension may never read or reset the token itself
        assert c.get("/api/extension/token", headers={**ext, "Authorization": f"Bearer {token}"}
                     ).status_code == 403
        # preflight passes
        pre = c.options("/api/messages", headers={
            **ext, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization"})
        assert pre.status_code == 200
        # reset gives a new token; the old one stops working; settings PUT cannot set it
        new = c.post("/api/extension/token", headers=own).json()["token"]
        assert new != token
        assert c.get("/api/extension/status", headers={**ext, "Authorization": f"Bearer {token}"}
                     ).status_code == 401
        c.put("/api/settings", json={"extension_token": "hacked"})
        assert c.get("/api/extension/status", headers={**ext, "Authorization": "Bearer hacked"}
                     ).status_code == 401
