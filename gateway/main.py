"""Life OS gateway — FastAPI app + the mobile app it serves.

Run:  .venv\\Scripts\\uvicorn gateway.main:create_app --factory --port 8787
The PWA lives at /app/ (surfaces/app/www). All endpoints work without any API keys
(deterministic offline fallbacks); ANTHROPIC_API_KEY upgrades them in place.
"""

import datetime
import json

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gateway import accounts
from gateway.auth import caller_graph, make_auth_dependency
from gateway.claude import ClaudeGateway
from gateway.modules_api import build_router
from gateway.router import route
from modules.horizon import gate, planner, retro, vision_intake
from modules.voiceos import capture as voice_capture
from substrate import ROOT, load_config
from substrate.bus import Bus
from substrate.graph import Graph, GraphError, ScopeError
from substrate.migrate import migrate

APP_DIR = ROOT / "surfaces" / "app" / "www"


class TextIn(BaseModel):
    text: str


class LogIn(BaseModel):
    n: int


class FocusIn(BaseModel):
    goal_id: str
    focus: bool = True


class CredentialsIn(BaseModel):
    handle: str
    password: str


def _g(request: Request) -> Graph:
    """The caller's own slice of the graph (config owner when there are no accounts)."""
    return caller_graph(request)


def _count(graph: Graph, sql: str, params: tuple = ()) -> int:
    row = graph._execute(sql, params).fetchone()
    return row["n"] if hasattr(row, "keys") or isinstance(row, dict) else row[0]


def _week_payload(graph: Graph) -> dict:
    week = planner.week_id()
    tasks = [
        {"n": i, "id": t["id"], "title": t["attrs"].get("title", ""),
         "if_then": t["attrs"].get("if_then", ""), "status": t["attrs"].get("status", "open")}
        for i, t in enumerate(planner.week_tasks(graph, week), 1)
    ]
    return {"week": week, "tasks": tasks}


def _label(kind: str, attrs: dict) -> str:
    if kind == "content":
        return (attrs.get("text") or attrs.get("type") or "")[:80]
    return attrs.get("title") or attrs.get("name") or attrs.get("type") or ""


def create_app(cfg: dict | None = None) -> FastAPI:
    cfg = cfg or load_config()
    conn = migrate(cfg)  # idempotent — ensures schema exists
    bus = Bus()
    graph = Graph(conn, bus, default_owner=cfg.get("owner", {}).get("id"))
    claude = ClaudeGateway(cfg)

    app = FastAPI(title="Life OS Gateway", version="0.2.0")
    app.add_middleware(  # the Capacitor app runs from capacitor:// — auth stays on the token
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    app.state.cfg = cfg
    app.state.graph = graph
    app.state.claude = claude

    @app.exception_handler(ScopeError)
    def _scope_denied(request: Request, exc: ScopeError):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(GraphError)
    def _graph_error(request: Request, exc: GraphError):
        """An id you may not touch is reported exactly like one that doesn't exist —
        no 500s, and no way to probe for other people's entities."""
        missing = "not found" in str(exc)
        return JSONResponse(status_code=404 if missing else 400, content={"detail": str(exc)})

    auth = make_auth_dependency(cfg.get("gateway", {}).get("auth_token", ""))
    app.include_router(build_router(auth))  # reconnect/convoy/memento/steward/vitals/ledger/calibre/hearth

    @app.get("/health")
    def health():
        """Liveness only — this is the one route that answers before you authenticate.

        It used to report the instance's total entity count. That was harmless on a private
        NucBox and is not on a public box: an unauthenticated caller could watch the number
        move and learn how much the system holds and when people use it. Anything that
        counts what's inside now lives behind auth on /v1/stats; what stays here is exactly
        what a load balancer, an uptime check and the PWA's mode badge need.
        """
        return {"ok": True, "env": cfg.get("env"), "claude": claude.available}

    @app.get("/v1/stats", dependencies=[Depends(auth)])
    def stats():
        return {"entities": _count(graph, "SELECT COUNT(*) AS n FROM entities"),
                "observations": _count(graph, "SELECT COUNT(*) AS n FROM observations")}

    @app.post("/v1/route", dependencies=[Depends(auth)])
    def route_text(body: TextIn):
        return route(body.text, claude=claude)

    # ---- Accounts --------------------------------------------------------
    # register/login are deliberately unauthenticated — they are how you get a token.

    @app.post("/v1/auth/register")
    def auth_register(body: CredentialsIn):
        try:
            return accounts.register(graph, body.handle, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/v1/auth/login")
    def auth_login(body: CredentialsIn):
        try:
            return accounts.login(graph, body.handle, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

    @app.get("/v1/auth/me", dependencies=[Depends(auth)])
    def auth_me(request: Request):
        caller = getattr(request.state, "caller", None)
        if not caller:
            return {"handle": None, "owner_id": graph.default_owner, "mode": "owner-key"}
        return {"handle": caller["handle"], "owner_id": caller["owner_id"],
                "account_id": caller["account_id"], "mode": "account",
                "sessions": accounts.sessions(graph, caller["account_id"])}

    @app.post("/v1/auth/logout", dependencies=[Depends(auth)])
    def auth_logout(request: Request, authorization: str = Header(default="")):
        token = authorization[len("Bearer "):].strip() if authorization.startswith("Bearer ") else ""
        return accounts.logout(graph, token)

    @app.post("/v1/auth/logout-everywhere", dependencies=[Depends(auth)])
    def auth_logout_all(request: Request):
        """The 'my phone is gone' button: cut every session for this account at once."""
        caller = getattr(request.state, "caller", None)
        if not caller:
            raise HTTPException(status_code=400, detail="not signed in with an account")
        return accounts.revoke_all(graph, caller["account_id"])

    # ---- Horizon ---------------------------------------------------------

    @app.get("/v1/vision", dependencies=[Depends(auth)])
    def list_visions(request: Request):
        session = _g(request).session("horizon", vision_intake.SCOPES)
        visions = session.find_entities("goal", {"level": "vision"})
        return {"visions": [{"id": v["id"], "title": v["attrs"].get("title", "")} for v in visions]}

    @app.post("/v1/vision", dependencies=[Depends(auth)])
    def vision(request: Request, body: TextIn):
        return vision_intake.intake(body.text, _g(request), claude=claude)

    @app.get("/v1/week", dependencies=[Depends(auth)])
    def week(request: Request):
        return _week_payload(_g(request))

    @app.get("/v1/goals", dependencies=[Depends(auth)])
    def goals(request: Request):
        return {"goals": planner.list_goals(_g(request))}

    @app.post("/v1/focus", dependencies=[Depends(auth)])
    def focus(request: Request, body: FocusIn):
        """Gate-first (T3): the focused goal leads next week's plan."""
        return planner.set_goal_focus(_g(request), body.goal_id, body.focus)

    @app.post("/v1/plan", dependencies=[Depends(auth)])
    def plan(request: Request):
        baseline = cfg.get("vitals", {}).get("energy_baseline", "tired")
        scoped = _g(request)
        planner.plan_week(scoped, claude=claude, energy_baseline=baseline)
        return _week_payload(scoped)

    @app.post("/v1/log", dependencies=[Depends(auth)])
    def log(request: Request, body: LogIn):
        try:
            title = planner.log_done(_g(request), body.n)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"done": title}

    @app.post("/v1/retro", dependencies=[Depends(auth)])
    def run_retro(request: Request):
        return retro.run_retro(_g(request), claude=claude)

    @app.get("/v1/today", dependencies=[Depends(auth)])
    def today(request: Request):
        scoped = _g(request)
        payload = _week_payload(scoped)
        session = scoped.session("gateway", {"events:read"})
        now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        upcoming = []
        for ev in session.find_entities("event", {"busy": True}, limit=200):
            try:
                start = datetime.datetime.fromisoformat(ev["attrs"].get("start", ""))
            except ValueError:
                continue
            if start >= now:
                upcoming.append({"start": ev["attrs"]["start"], "end": ev["attrs"].get("end", ""),
                                 "title": ev["attrs"].get("title", "")})
        payload["events"] = sorted(upcoming, key=lambda e: e["start"])[:5]
        return payload

    # ---- VoiceOS ---------------------------------------------------------

    @app.post("/v1/capture", dependencies=[Depends(auth)])
    def do_capture(request: Request, body: TextIn):
        return voice_capture.capture(body.text, _g(request), claude=claude)

    @app.get("/v1/parked", dependencies=[Depends(auth)])
    def parked(request: Request):
        """Distraction sink (T3): captured-not-abandoned project ideas."""
        return {"parked": voice_capture.list_parked(_g(request))}

    @app.get("/v1/gate", dependencies=[Depends(auth)])
    def gate_status(request: Request):
        """Doubt rule (T3): honest v0.1-gate progress from real counts."""
        return gate.gate_status(_g(request))

    # ---- Graph -----------------------------------------------------------

    @app.get("/v1/graph", dependencies=[Depends(auth)])
    def graph_summary(request: Request):
        scoped = _g(request)
        owner = scoped.default_owner
        where, params = ("WHERE owner_id = ?", (owner,)) if owner else ("", ())
        counts = {r["kind"]: r["n"] for r in scoped._execute(
            f"SELECT kind, COUNT(*) AS n FROM entities {where} GROUP BY kind", params).fetchall()}
        recent = [
            {"kind": r["kind"], "label": _label(r["kind"], json.loads(r["attrs"])), "created_at": r["created_at"]}
            for r in scoped._execute(
                f"SELECT kind, attrs, created_at FROM entities {where} "
                f"ORDER BY created_at DESC LIMIT 15", params).fetchall()
        ]
        return {"entities": sum(counts.values()), "counts": counts,
                "edges": _count(scoped, "SELECT COUNT(*) AS n FROM edges"),
                "observations": _count(scoped, "SELECT COUNT(*) AS n FROM observations"),
                "recent": recent}

    @app.get("/v1/export", dependencies=[Depends(auth)])
    def export(request: Request):
        """Law 2: full export always. The graph is the user's."""
        scoped = _g(request)
        owner = scoped.default_owner

        def rows(table):
            if owner and table == "entities":
                return [dict(r) for r in scoped._execute(
                    "SELECT * FROM entities WHERE owner_id = ?", (owner,)).fetchall()]
            return [dict(r) for r in scoped._execute(f"SELECT * FROM {table}").fetchall()]
        entities = rows("entities")
        for e in entities:
            e["attrs"] = json.loads(e["attrs"]) if isinstance(e["attrs"], str) else e["attrs"]
            e.pop("embedding", None)
        edges = rows("edges")
        for e in edges:
            e["attrs"] = json.loads(e["attrs"]) if isinstance(e["attrs"], str) else e["attrs"]
        return {"exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "entities": entities, "edges": edges, "observations": rows("observations")}

    # ---- the app itself --------------------------------------------------

    if APP_DIR.exists():
        app.mount("/app", StaticFiles(directory=str(APP_DIR), html=True), name="app")

        @app.get("/", include_in_schema=False)
        def index():
            return RedirectResponse("/app/")

    return app
