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
                app.state.tools = DirectTools(app.state.con)
        else:
            app.state.tools = DirectTools(app.state.con)
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
            if k in {"provider", "endpoint", "model", "api_key", "user_name", "user_language"}:
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
        return {"id": db.contact_add(app.state.con, c.name, c.locale, c.notes)}

    @app.delete("/api/contacts/{cid}")
    def contact_delete(cid: str) -> dict[str, bool]:
        db.contact_delete(app.state.con, cid)
        return {"ok": True}

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
        return demo.SAMPLE_MESSAGES

    # -- UI ------------------------------------------------------------------

    if (STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="ui")

    return app
