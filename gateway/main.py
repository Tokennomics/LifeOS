"""Life OS gateway — FastAPI app + the mobile app it serves.

Run:  .venv\\Scripts\\uvicorn gateway.main:create_app --factory --port 8787
The PWA lives at /app/ (surfaces/app/www). All endpoints work without any API keys
(deterministic offline fallbacks); ANTHROPIC_API_KEY upgrades them in place.
"""

import datetime
import json

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gateway.auth import make_auth_dependency
from gateway.claude import ClaudeGateway
from gateway.modules_api import build_router
from gateway.router import route
from modules.horizon import gate, planner, retro, vision_intake
from modules.voiceos import capture as voice_capture
from substrate import ROOT, load_config
from substrate.bus import Bus
from substrate.graph import Graph
from substrate.migrate import migrate

APP_DIR = ROOT / "surfaces" / "app" / "www"


class TextIn(BaseModel):
    text: str


class LogIn(BaseModel):
    n: int


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
    auth = make_auth_dependency(cfg.get("gateway", {}).get("auth_token", ""))
    app.include_router(build_router(auth))  # reconnect/convoy/memento/steward/vitals/ledger/calibre/hearth

    @app.get("/health")
    def health():
        return {"ok": True, "env": cfg.get("env"),
                "entities": _count(graph, "SELECT COUNT(*) AS n FROM entities"),
                "claude": claude.available}

    @app.post("/v1/route", dependencies=[Depends(auth)])
    def route_text(body: TextIn):
        return route(body.text, claude=claude)

    # ---- Horizon ---------------------------------------------------------

    @app.get("/v1/vision", dependencies=[Depends(auth)])
    def list_visions():
        session = graph.session("horizon", vision_intake.SCOPES)
        visions = session.find_entities("goal", {"level": "vision"})
        return {"visions": [{"id": v["id"], "title": v["attrs"].get("title", "")} for v in visions]}

    @app.post("/v1/vision", dependencies=[Depends(auth)])
    def vision(body: TextIn):
        return vision_intake.intake(body.text, graph, claude=claude)

    @app.get("/v1/week", dependencies=[Depends(auth)])
    def week():
        return _week_payload(graph)

    @app.post("/v1/plan", dependencies=[Depends(auth)])
    def plan():
        baseline = cfg.get("vitals", {}).get("energy_baseline", "tired")
        planner.plan_week(graph, claude=claude, energy_baseline=baseline)
        return _week_payload(graph)

    @app.post("/v1/log", dependencies=[Depends(auth)])
    def log(body: LogIn):
        try:
            title = planner.log_done(graph, body.n)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"done": title}

    @app.post("/v1/retro", dependencies=[Depends(auth)])
    def run_retro():
        return retro.run_retro(graph, claude=claude)

    @app.get("/v1/today", dependencies=[Depends(auth)])
    def today():
        payload = _week_payload(graph)
        session = graph.session("gateway", {"events:read"})
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
    def do_capture(body: TextIn):
        return voice_capture.capture(body.text, graph, claude=claude)

    @app.get("/v1/parked", dependencies=[Depends(auth)])
    def parked():
        """Distraction sink (T3): captured-not-abandoned project ideas."""
        return {"parked": voice_capture.list_parked(graph)}

    @app.get("/v1/gate", dependencies=[Depends(auth)])
    def gate_status():
        """Doubt rule (T3): honest v0.1-gate progress from real counts."""
        return gate.gate_status(graph)

    # ---- Graph -----------------------------------------------------------

    @app.get("/v1/graph", dependencies=[Depends(auth)])
    def graph_summary():
        counts = {r["kind"]: r["n"] for r in
                  graph._execute("SELECT kind, COUNT(*) AS n FROM entities GROUP BY kind").fetchall()}
        recent = [
            {"kind": r["kind"], "label": _label(r["kind"], json.loads(r["attrs"])), "created_at": r["created_at"]}
            for r in graph._execute("SELECT kind, attrs, created_at FROM entities ORDER BY created_at DESC LIMIT 15").fetchall()
        ]
        return {"entities": sum(counts.values()), "counts": counts,
                "edges": _count(graph, "SELECT COUNT(*) AS n FROM edges"),
                "observations": _count(graph, "SELECT COUNT(*) AS n FROM observations"),
                "recent": recent}

    @app.get("/v1/export", dependencies=[Depends(auth)])
    def export():
        """Law 2: full export always. The graph is the user's."""
        def rows(table):
            return [dict(r) for r in graph._execute(f"SELECT * FROM {table}").fetchall()]
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
