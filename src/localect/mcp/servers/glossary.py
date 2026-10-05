from mcp.server.mcpserver import MCPServer

from ... import db
from . import open_db


def make_server(con=None) -> MCPServer:
    con = con or open_db()
    server = MCPServer(name="localect-glossary",
                       instructions="Brand terms, do-not-translate items, preferred renderings.")

    @server.tool(description="Glossary entries whose term appears in the text and apply to "
                             "the target language.")
    def lookup(text: str, language: str) -> list[dict]:
        return db.glossary_lookup(con, text, language)

    @server.tool(description="All terms that must never be translated.")
    def do_not_translate() -> list[str]:
        return [g["term"] for g in db.glossary_list(con) if g["do_not_translate"]]

    return server


if __name__ == "__main__":
    make_server().run("stdio")
