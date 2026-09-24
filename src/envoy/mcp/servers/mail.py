from mcp.server.mcpserver import MCPServer

from ... import db
from . import open_db


def make_server(con=None) -> MCPServer:
    con = con or open_db()
    server = MCPServer(name="envoy-mail",
                       instructions="The user's past mail, imported from exports or captured "
                                    "with consent. Facts and voice, each with a date. Never "
                                    "overrides the glossary or knowledge base.")

    @server.tool(description="Paragraphs of past mail with similar vocabulary; newest first "
                             "on a tie, mail with the given contact ranked above the rest.")
    def search_mail(query: str, language: str | None = None, contact_email: str = "",
                    limit: int = 5) -> list[dict]:
        return db.mail_search(con, query, language, contact_email, limit)

    return server


if __name__ == "__main__":
    make_server().run("stdio")
