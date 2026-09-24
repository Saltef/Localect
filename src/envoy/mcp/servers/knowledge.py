from mcp.server.mcpserver import MCPServer

from ...memory import search as memsearch
from . import open_db, open_embedder


def make_server(con=None, embedder=None) -> MCPServer:
    con = con or open_db()
    embedder = embedder or open_embedder()
    server = MCPServer(name="envoy-knowledge",
                       instructions="The user's own facts, policies, and FAQ.")

    @server.tool(description="Search the knowledge base. Returns snippets with ids and offsets.")
    def search(query: str, limit: int = 5) -> list[dict]:
        return memsearch.knowledge_search(con, embedder, query, limit)

    return server


if __name__ == "__main__":
    make_server().run("stdio")
