from fastapi.testclient import TestClient

from envoy import db
from envoy.app import create_app
from envoy.locales import seed_locales


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
    monkeypatch.setenv("ENVOY_DATA_DIR", str(tmp_path))
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
