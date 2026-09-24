"""The FastAPI application: the JSON API plus the bundled UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, db, demo
from .config import Settings
from .locales import seed_locales
from .mcp.client import MCPTools
from .memory.embed import build_embedder, describe
from .memory.index import index_all, index_message
from .models import build_model
from .pipeline import PipelineError, compose
from .schemas import ComposeRequest, ComposeResponse, LocaleProfile
from .tools import DirectTools

log = logging.getLogger("envoy")
STATIC = Path(__file__).parent / "static"


class GlossaryIn(BaseModel):
    term: str
    rendering: str = ""
    language: str = "*"
    do_not_translate: bool = False
    notes: str = ""


class ContactIn(BaseModel):
    name: str
    locale: str
    notes: str = ""
    gender: str = "unknown"  # unknown | female | male; picks the gendered greeting where needed
    email: str = ""  # ties the contact to imported mail


class ImportIn(BaseModel):
    paths: list[str]


class FactPatch(BaseModel):
    status: str | None = None  # auto | confirmed | rejected
    statement: str | None = None
    value: str | None = None
    topic: str | None = None


class MessageIn(BaseModel):
    """One message captured with the user's consent (the extension, or a
    client that already has the text). Same record the importer builds."""
    text: str
    subject: str = ""
    from_addr: str = ""
    from_name: str = ""
    to_addrs: list[str] = []
    date: str = ""
    thread_id: str = ""
    external_id: str = ""
    is_mine: bool | None = None  # None: decided from settings.user_email
    origin: str = "capture"


class KnowledgeIn(BaseModel):
    title: str
    text: str


def create_app(settings: Settings | None = None, con=None, model=None, tools=None,
               use_mcp: bool = True) -> FastAPI:
    settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.con = con if con is not None else db.connect(settings.db_path)
        seed_locales(app.state.con)
        app.state.model = model or build_model(settings)
        app.state.mcp = False
        if tools is not None:
            app.state.tools = tools
        elif use_mcp and con is None:
            mcp_tools = MCPTools(settings.db_path)
            try:
                await mcp_tools.start()
                app.state.tools = mcp_tools
                app.state.mcp = True
            except Exception as e:  # noqa: BLE001 - fall back, never fail to start
                log.warning("MCP servers unavailable (%s); using in-process tools", e)
                app.state.tools = DirectTools(app.state.con, build_embedder(settings))
        else:
            app.state.tools = DirectTools(app.state.con, build_embedder(settings))
        try:
            yield
        finally:
            if app.state.mcp:
                await app.state.tools.stop()

    app = FastAPI(title="Envoy", version=__version__, lifespan=lifespan)

    # -- health & settings ---------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        s: Settings = app.state.settings
        return {"ok": True, "version": __version__, "provider": s.provider,
                "model": app.state.model.name, "mcp": app.state.mcp}

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return app.state.settings.public()

    @app.put("/api/settings")
    def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        s: Settings = app.state.settings
        for k, v in patch.items():
            if k in {"provider", "endpoint", "model", "api_key", "user_name", "user_email",
                     "user_language", "embed_model"}:
                if k == "api_key" and v in ("", "set"):
                    continue  # the UI sends the masked value back; keep the stored key
                setattr(s, k, v)
        s.save()
        app.state.model = build_model(s)
        return s.public()

    @app.get("/api/settings/check")
    def check_settings() -> dict[str, Any]:
        m = app.state.model
        if hasattr(m, "check"):
            return m.check()
        return {"ok": True, "provider": app.state.settings.provider, "models": [],
                "has_model": True,
                "note": "stub provider: deterministic, runs offline, not a language model"}

    @app.get("/api/models")
    def list_models() -> dict[str, Any]:
        """Models the configured endpoint can serve, for the pickers."""
        m = app.state.model
        if not hasattr(m, "list_models"):
            return {"models": [], "current": m.name,
                    "note": "stub provider has no models to pick from"}
        try:
            return {"models": m.list_models(), "current": m.model}
        except Exception as e:  # noqa: BLE001 - endpoint without a model list
            return {"models": [], "current": m.model, "note": str(e)[:200]}

    def _model_for(req: ComposeRequest):
        m = app.state.model
        if req.model and hasattr(m, "with_model") and req.model != m.model:
            return m.with_model(req.model)
        return m

    # -- compose -------------------------------------------------------------

    @app.post("/api/compose", response_model=ComposeResponse)
    async def api_compose(req: ComposeRequest) -> ComposeResponse:
        if not req.message.strip():
            raise HTTPException(400, "message is empty")
        try:
            result = await compose(req, settings=app.state.settings, model=_model_for(req),
                                   tools=app.state.tools, con=app.state.con)
        except PipelineError as e:
            raise HTTPException(502, str(e)) from e
        return ComposeResponse(result=result)

    # -- glossary ------------------------------------------------------------

    @app.get("/api/glossary")
    def glossary_list() -> list[dict[str, Any]]:
        return db.glossary_list(app.state.con)

    @app.post("/api/glossary")
    def glossary_add(item: GlossaryIn) -> dict[str, str]:
        gid = db.glossary_add(app.state.con, item.term, item.rendering, item.language,
                              item.do_not_translate, item.notes)
        return {"id": gid}

    @app.delete("/api/glossary/{gid}")
    def glossary_delete(gid: str) -> dict[str, bool]:
        db.glossary_delete(app.state.con, gid)
        return {"ok": True}

    # -- locales -------------------------------------------------------------

    @app.get("/api/locales")
    def locales() -> list[LocaleProfile]:
        return db.locale_list(app.state.con)

    @app.get("/api/locales/{locale}")
    def locale_get(locale: str) -> LocaleProfile:
        p = db.locale_get(app.state.con, locale)
        if not p:
            raise HTTPException(404, "no such locale")
        return p

    @app.put("/api/locales/{locale}")
    def locale_put(locale: str, profile: LocaleProfile) -> LocaleProfile:
        profile.locale = locale
        db.locale_upsert(app.state.con, profile)
        return profile

    # -- contacts ------------------------------------------------------------

    @app.get("/api/contacts")
    def contacts() -> list[dict[str, Any]]:
        return db.contact_list(app.state.con)

    @app.post("/api/contacts")
    def contact_add(c: ContactIn) -> dict[str, str]:
        return {"id": db.contact_add(app.state.con, c.name, c.locale, c.notes, c.gender,
                                     c.email)}

    @app.delete("/api/contacts/{cid}")
    def contact_delete(cid: str) -> dict[str, bool]:
        db.contact_delete(app.state.con, cid)
        return {"ok": True}

    # -- memory: the user's past mail ------------------------------------------

    @app.get("/api/messages")
    def messages(q: str = "", limit: int = 100) -> dict[str, Any]:
        return {"counts": db.message_count(app.state.con),
                "messages": db.message_list(app.state.con, limit, q)}

    @app.get("/api/messages/{mid}")
    def message(mid: str) -> dict[str, Any]:
        m = db.message_get(app.state.con, mid)
        if not m:
            raise HTTPException(404, "no such message")
        return m

    @app.post("/api/messages")
    async def message_add(m: MessageIn) -> dict[str, Any]:
        from .memory.clean import clean_body
        from .memory.parse import now_iso
        from .models.stub import detect_language

        s: Settings = app.state.settings
        text = clean_body(m.text)
        if not text:
            raise HTTPException(400, "the message has no text once quotes are removed")
        mine = m.is_mine if m.is_mine is not None else m.from_addr.lower() in s.my_addresses
        mid = db.message_add(
            app.state.con, text=text, external_id=m.external_id, thread_id=m.thread_id,
            date=m.date or now_iso(), from_addr=m.from_addr, from_name=m.from_name,
            to_addrs=",".join(a.lower() for a in m.to_addrs), subject=m.subject, is_mine=mine,
            language=detect_language(text), origin=m.origin or "capture")
        app.state.con.commit()
        facts_found = 0
        if mid:
            index_message(app.state.con, build_embedder(s), mid)
            # Read the new message for facts right away; a failure here must
            # not lose the capture, so it is reported, not raised.
            from .agents.stage import StageError
            from .memory.facts import extract_message

            try:
                facts_found = await extract_message(app.state.con, app.state.model,
                                                    db.message_get(app.state.con, mid))
            except StageError:
                facts_found = -1
        return {"id": mid, "stored": mid is not None, "facts": facts_found}

    @app.delete("/api/messages/{mid}")
    def message_delete(mid: str) -> dict[str, bool]:
        db.message_delete(app.state.con, mid)
        return {"ok": True}

    @app.post("/api/import")
    def import_files(body: ImportIn) -> dict[str, Any]:
        """Import mail exports and documents from paths on this machine."""
        from dataclasses import asdict

        from .memory import import_paths

        s: Settings = app.state.settings
        missing = [p for p in body.paths if not Path(p).exists()]
        if missing:
            raise HTTPException(400, f"not found: {', '.join(missing)}")
        report = import_paths(app.state.con, body.paths, s.my_addresses)
        indexed = index_all(app.state.con, build_embedder(s))
        return {**asdict(report), "summary": report.summary(), "indexed": indexed,
                "counts": db.message_count(app.state.con)}

    @app.get("/api/memory")
    def memory_status() -> dict[str, Any]:
        s: Settings = app.state.settings
        return {"embedder": describe(build_embedder(s)),
                "counts": db.message_count(app.state.con),
                "vectors": db.embedding_count(app.state.con),
                "facts": db.fact_count(app.state.con),
                "unextracted": len(db.messages_unextracted(app.state.con)),
                "conflicts": db.facts_conflicts(app.state.con)}

    @app.get("/api/facts")
    def facts(q: str = "", party: str = "", status: str = "", limit: int = 200
              ) -> list[dict[str, Any]]:
        return db.fact_list(app.state.con, q, party, status, limit)

    @app.put("/api/facts/{fid}")
    def fact_patch(fid: str, patch: FactPatch) -> dict[str, Any]:
        from .memory.facts import topic_key

        if patch.status is not None and patch.status not in ("auto", "confirmed", "rejected"):
            raise HTTPException(400, "status must be auto, confirmed or rejected")
        fields = patch.model_dump()
        if patch.topic is not None:
            fields["topic_key"] = topic_key(patch.topic)
        out = db.fact_update(app.state.con, fid, **fields)
        if not out:
            raise HTTPException(404, "no such fact")
        return out

    @app.delete("/api/facts/{fid}")
    def fact_delete(fid: str) -> dict[str, bool]:
        db.fact_delete(app.state.con, fid)
        return {"ok": True}

    @app.post("/api/extract")
    async def extract_now(limit: int = 1000) -> dict[str, Any]:
        from dataclasses import asdict

        from .memory.facts import extract_pending

        report = await extract_pending(app.state.con, app.state.model, limit)
        return {**asdict(report), "facts_total": db.fact_count(app.state.con)}

    @app.post("/api/index")
    def index_now() -> dict[str, Any]:
        s: Settings = app.state.settings
        emb = build_embedder(s)
        return {"embedder": describe(emb), "indexed": index_all(app.state.con, emb)}

    # -- knowledge -----------------------------------------------------------

    @app.get("/api/knowledge")
    def knowledge() -> list[dict[str, Any]]:
        return db.knowledge_list(app.state.con)

    @app.post("/api/knowledge")
    def knowledge_add(k: KnowledgeIn) -> dict[str, str]:
        return {"id": db.knowledge_add(app.state.con, k.title, k.text)}

    @app.delete("/api/knowledge/{kid}")
    def knowledge_delete(kid: str) -> dict[str, bool]:
        db.knowledge_delete(app.state.con, kid)
        return {"ok": True}

    # -- history -------------------------------------------------------------

    @app.get("/api/history")
    def history() -> list[dict[str, Any]]:
        return db.history_list(app.state.con)

    @app.get("/api/history/{rid}")
    def history_get(rid: str) -> dict[str, Any]:
        r = db.history_get(app.state.con, rid)
        if not r:
            raise HTTPException(404, "no such result")
        return r

    # -- demo ----------------------------------------------------------------

    @app.post("/api/demo")
    def load_demo() -> dict[str, int]:
        return demo.seed_demo(app.state.con)

    @app.get("/api/demo/messages")
    def demo_messages() -> list[dict[str, str]]:
        return [{"label": s["label"], "text": s["text"]} for s in demo.SAMPLE_MESSAGES]

    # -- UI ------------------------------------------------------------------

    if (STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="ui")

    return app
