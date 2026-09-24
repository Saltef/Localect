import tempfile
from pathlib import Path

from envoy import db
from envoy.mcp.client import MCPTools


async def test_all_five_servers_over_stdio():
    path = Path(tempfile.mkdtemp()) / "e.db"
    con = db.connect(path)
    db.glossary_add(con, "SkyPack", do_not_translate=True)
    db.knowledge_add(con, "Ship", "Orders ship within 2 business days.")
    db.history_add(con, "{}", "r1", "2026-01-01T00:00:00", "when does it ship", "en-US",
                   "ready", "It ships in 2 days.", "c1")
    db.message_add(con, text="The return window is 30 days from delivery.", subject="Returns",
                   date="2025-09-10T10:00:00Z", from_addr="safea@example.com", is_mine=True,
                   to_addrs="layla@shop.example", language="en")
    con.commit()
    tools = MCPTools(path)
    await tools.start()
    try:
        listed = await tools.list_tools()
        assert listed == {"glossary": ["lookup", "do_not_translate"], "knowledge": ["search"],
                          "history": ["search_past"], "thread": ["get_thread"],
                          "mail": ["search_mail"]}
        g = await tools.glossary_lookup("my SkyPack", "ar")
        assert g[0].kind == "glossary" and g[0].meta["term"] == "SkyPack"
        k = await tools.knowledge_search("pedido envío")
        assert k and k[0].id.startswith("kb:") and "start" in k[0].meta
        h = await tools.history_search("ship", "en")
        assert h and h[0].text == "It ships in 2 days."
        t = await tools.thread("c1")
        assert t and "They wrote" in t[0].text
        # cross-lingual through the hybrid search inside the mail server
        m = await tools.mail_search("prazo de devolução", "en", "layla@shop.example")
        assert m and m[0].id.startswith("ml:") and m[0].kind == "mail"
        assert m[0].meta["said"] == "you wrote on 2025-09-10, re: Returns"
        assert m[0].text == "The return window is 30 days from delivery."
    finally:
        await tools.stop()
