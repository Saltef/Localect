import tempfile
from pathlib import Path

from envoy import db
from envoy.mcp.client import MCPTools


async def test_all_four_servers_over_stdio():
    path = Path(tempfile.mkdtemp()) / "e.db"
    con = db.connect(path)
    db.glossary_add(con, "SkyPack", do_not_translate=True)
    db.knowledge_add(con, "Ship", "Orders ship within 2 business days.")
    db.history_add(con, "{}", "r1", "2026-01-01T00:00:00", "when does it ship", "en-US",
                   "ready", "It ships in 2 days.", "c1")
    tools = MCPTools(path)
    await tools.start()
    try:
        listed = await tools.list_tools()
        assert listed == {"glossary": ["lookup", "do_not_translate"], "knowledge": ["search"],
                          "history": ["search_past"], "thread": ["get_thread"]}
        g = await tools.glossary_lookup("my SkyPack", "ar")
        assert g[0].kind == "glossary" and g[0].meta["term"] == "SkyPack"
        k = await tools.knowledge_search("pedido envío")
        assert k and k[0].id.startswith("kb:") and "start" in k[0].meta
        h = await tools.history_search("ship", "en")
        assert h and h[0].text == "It ships in 2 days."
        t = await tools.thread("c1")
        assert t and "They wrote" in t[0].text
    finally:
        await tools.stop()
