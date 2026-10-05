"""The FastAPI application: the JSON API plus the bundled UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, auth, db, demo
from .config import Settings, data_dir
from .locales import seed_locales
from .mcp.client import MCPTools
from .memory.embed import build_embedder, describe
from .memory.index import index_all, index_message
from .models import build_model
from .pipeline import PipelineError, compose
from .schemas import ComposeRequest, ComposeResponse, LocaleProfile
from .tools import DirectTools

log = logging.getLogger("localect")
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


class LoginIn(BaseModel):
    password: str


class ImportIn(BaseModel):
    paths: list[str]


class ExclusionIn(BaseModel):
    kind: str  # thread | address
    value: str


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


def is_extension_origin(origin: str) -> bool:
    return origin.startswith(("chrome-extension://", "moz-extension://", "safari-web-extension://"))


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
        app.state.secret = auth.server_secret(data_dir())
        app.state.limit = auth.RateLimit(settings.public_hourly, settings.public_daily)
        # Visitors never touch the owner's database: the demo lives in memory.
        app.state.demo_con = None
        if settings.public_mode == "demo":
            dcon = db.connect()
            seed_locales(dcon)
            demo.seed_demo(dcon)
            app.state.demo_con = dcon
            app.state.demo_model = (app.state.model if settings.public_model == "configured"
                                    else build_model(Settings(provider="stub",
                                                              user_name=settings.user_name)))
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

    app = FastAPI(title="Localect", version=__version__, lifespan=lifespan)

    # Who may call the API from a browser. Localect listens on localhost, and any
    # web page can make a request to localhost, so a request that carries an
    # Origin must be the app's own page or the paired extension. Requests with
    # no Origin (the CLI, curl, the tests) are unaffected.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(chrome|moz|safari-web)-extension://.*$",
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def _is_owner(request: Request) -> bool:
        """The owner: no password set (a laptop), a valid session cookie, or the
        extension's token."""
        s: Settings = app.state.settings
        if not s.auth_required:
            return True
        if auth.session_valid(app.state.secret, request.cookies.get(auth.COOKIE)):
            return True
        bearer = request.headers.get("authorization", "")
        return bool(s.extension_token) and bearer == f"Bearer {s.extension_token}"

    def _client_ip(request: Request) -> str:
        if app.state.settings.trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "?"

    # Paths anyone may call (to find out they must sign in, and to do so), and
    # the ones a visitor may use in public demo mode. Everything else is the owner's.
    ALWAYS = {"/api/health", "/api/login", "/api/logout"}
    DEMO_PATHS = ALWAYS | {"/api/compose", "/api/demo/messages", "/api/locales"}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        origin = request.headers.get("origin", "")
        if origin and request.method != "OPTIONS" and path.startswith("/api/"):
            # A browser request must come from the app's own page (same host,
            # whatever scheme the proxy in front terminates) or the paired extension.
            own_host = origin.split("://", 1)[-1].rstrip("/") == request.headers.get("host", "")
            if not own_host:
                if not is_extension_origin(origin):
                    return JSONResponse({"detail": "this origin may not call Localect"}, 403)
                token = app.state.settings.extension_token
                bearer = request.headers.get("authorization", "")
                if not token or bearer != f"Bearer {token}":
                    return JSONResponse({"detail": "pair the extension: paste the token from "
                                                   "Localect's Settings page"}, 401)
                if path.startswith("/api/extension/token"):
                    return JSONResponse({"detail": "not for the extension"}, 403)
        if path.startswith("/api/") and request.method != "OPTIONS":
            owner = _is_owner(request)
            request.state.owner = owner
            allowed = DEMO_PATHS if app.state.settings.public_mode == "demo" else ALWAYS
            if not owner and path not in allowed:
                return JSONResponse({"detail": "sign in"}, 401)
        return await call_next(request)

    # -- login ---------------------------------------------------------------

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
        s: Settings = app.state.settings
        if not s.auth_required:
            return {"ok": True, "owner": True}
        if not app.state.limit.take("login:" + _client_ip(request)):
            raise HTTPException(429, "too many attempts; try later")
        if not auth.check_password(body.password, s.owner_password_hash):
            raise HTTPException(401, "wrong password")
        secure = s.trust_proxy and request.headers.get("x-forwarded-proto", "") == "https"
        response.set_cookie(auth.COOKIE, auth.issue_session(app.state.secret), httponly=True,
                            samesite="lax", secure=secure, max_age=auth.SESSION_DAYS * 86400,
                            path="/")
        return {"ok": True, "owner": True}

    @app.post("/api/logout")
    def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(auth.COOKIE, path="/")
        return {"ok": True}

    # -- health & settings ---------------------------------------------------

    @app.get("/api/extension/status")
    def extension_status() -> dict[str, Any]:
        """What the extension shows in its indicator: is memory capturing, and who
        the user is (to mark their own messages)."""
        s: Settings = app.state.settings
        return {"ok": True, "version": __version__, "capture": s.memory_capture,
                "user_email": s.user_email, "user_name": s.user_name,
                "counts": db.message_count(app.state.con)}

    @app.get("/api/extension/token")
    def extension_token() -> dict[str, str]:
        """The pairing token, for the Settings page only (the origin guard keeps
        extension origins out of this path)."""
        return {"token": app.state.settings.ensure_extension_token()}

    @app.post("/api/extension/token")
    def extension_token_reset() -> dict[str, str]:
        s: Settings = app.state.settings
        s.extension_token = ""
        return {"token": s.ensure_extension_token()}

    @app.get("/api/health")
    def health(request: Request) -> dict[str, Any]:
        s: Settings = app.state.settings
        owner = getattr(request.state, "owner", True)
        out = {"ok": True, "version": __version__, "provider": s.provider,
               "model": app.state.model.name, "mcp": app.state.mcp,
               "auth_required": s.auth_required, "owner": owner,
               "public_mode": s.public_mode}
        if not owner:
            # A stranger learns nothing about the owner's model; a demo visitor
            # learns what the demo runs on and how many tries remain.
            out.update({"provider": "", "model": "", "mcp": False})
            if s.public_mode == "demo":
                hourly, daily = app.state.limit.remaining(_client_ip(request))
                out.update({"provider": app.state.demo_model.name.split(":")[0],
                            "model": app.state.demo_model.name,
                            "tries_left": min(hourly, daily)})
        return out

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return app.state.settings.public()

    @app.put("/api/settings")
    def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        s: Settings = app.state.settings
        for k, v in patch.items():
            if k in {"provider", "endpoint", "model", "api_key", "user_name", "user_email",
                     "user_language", "embed_model", "memory_capture"}:  # never the token
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
    async def api_compose(req: ComposeRequest, request: Request) -> ComposeResponse:
        if not req.message.strip():
            raise HTTPException(400, "message is empty")
        if len(req.message) > 20000:
            raise HTTPException(413, "message too long")
        if getattr(request.state, "owner", True):
            con, tools, model = app.state.con, app.state.tools, _model_for(req)
        else:
            # A visitor: the demo store only, the public model, capped, nothing kept.
            if not app.state.limit.take(_client_ip(request)):
                raise HTTPException(429, "the public demo has reached its limit; try later")
            con = app.state.demo_con
            tools = DirectTools(con, build_embedder(Settings(provider="stub")))
            model = app.state.demo_model
            req = ComposeRequest(message=req.message, locale=req.locale)
        try:
            result = await compose(req, settings=app.state.settings, model=model, tools=tools,
                                   con=con)
        except PipelineError as e:
            raise HTTPException(502, str(e)) from e
        if con is app.state.demo_con:
            db.history_delete(con, result.id)
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
        return {**m, "facts": db.facts_for_message(app.state.con, mid)}

    @app.get("/api/exclusions")
    def exclusions() -> list[dict[str, Any]]:
        return db.exclusion_list(app.state.con)

    @app.post("/api/exclusions")
    def exclusion_add(x: ExclusionIn) -> dict[str, Any]:
        from .memory.parse import now_iso

        try:
            xid = db.exclusion_add(app.state.con, x.kind, x.value, now_iso())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"id": xid, "counts": db.message_count(app.state.con)}

    @app.delete("/api/exclusions/{xid}")
    def exclusion_delete(xid: str) -> dict[str, Any]:
        db.exclusion_delete(app.state.con, xid)
        return {"ok": True, "counts": db.message_count(app.state.con)}

    @app.post("/api/messages")
    async def message_add(m: MessageIn) -> dict[str, Any]:
        from .memory.clean import clean_body
        from .memory.parse import now_iso
        from .models.stub import detect_language

        s: Settings = app.state.settings
        if not s.memory_capture:
            return {"id": None, "stored": False, "facts": 0, "reason": "capture is paused"}
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
                "capture": s.memory_capture,
                "exclusions": len(db.exclusion_list(app.state.con)),
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
