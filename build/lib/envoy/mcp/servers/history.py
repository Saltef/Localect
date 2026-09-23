from mcp.server.mcpserver import MCPServer

from ... import db
from . import open_db


def make_server(con=None) -> MCPServer:
    con = con or open_db()
    server = MCPServer(name="envoy-history",
                       instructions="Past replies, for voice and precedent. Never overrides "
                                    "the glossary or knowledge base.")

    @server.tool(description="Past final replies with similar vocabulary.")
    def search_past(query: str, language: str | None = None, limit: int = 3) -> list[dict]:
        return db.history_search(con, query, language, limit)

    return server


if __name__ == "__main__":
    make_server().run("stdio")
