from mcp.server.mcpserver import MCPServer

from ... import db
from . import open_db


def make_server(con=None) -> MCPServer:
    con = con or open_db()
    server = MCPServer(name="envoy-thread",
                       instructions="The conversation so far with one contact.")

    @server.tool(description="Recent exchanges with a contact, oldest first.")
    def get_thread(contact_id: str, limit: int = 5) -> list[dict]:
        return db.history_thread(con, contact_id, limit)

    return server


if __name__ == "__main__":
    make_server().run("stdio")
