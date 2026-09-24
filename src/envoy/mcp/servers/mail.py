from mcp.server.mcpserver import MCPServer

from ...memory import search
from . import open_db, open_embedder


def make_server(con=None, embedder=None) -> MCPServer:
    con = con or open_db()
    embedder = embedder or open_embedder()
    server = MCPServer(name="envoy-mail",
                       instructions="The user's past mail, imported from exports or captured "
                                    "with consent. Facts and voice, each with a date. Never "
                                    "overrides the glossary or knowledge base.")

    @server.tool(description="Paragraphs of past mail with similar vocabulary; newest first "
                             "on a tie, mail with the given contact ranked above the rest.")
    def search_mail(query: str, language: str | None = None, contact_email: str = "",
                    limit: int = 5) -> list[dict]:
        return search.mail_search(con, embedder, query, language, contact_email, limit)

    return server


if __name__ == "__main__":
    make_server().run("stdio")
