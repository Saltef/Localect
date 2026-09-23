from mcp.server.mcpserver import MCPServer

from ... import db
from . import open_db


def make_server(con=None) -> MCPServer:
    con = con or open_db()
    server = MCPServer(name="envoy-knowledge",
                       instructions="The user's own facts, policies, and FAQ.")

    @server.tool(description="Search the knowledge base. Returns snippets with ids and offsets.")
    def search(query: str, limit: int = 5) -> list[dict]:
        return db.knowledge_search(con, query, limit)

    return server


if __name__ == "__main__":
    make_server().run("stdio")
