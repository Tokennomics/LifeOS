"""Life OS gateway — FastAPI app.

Run:  .venv\\Scripts\\uvicorn gateway.main:create_app --factory --port 8787
"""

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from gateway.auth import make_auth_dependency
from gateway.claude import ClaudeGateway
from gateway.router import route
from modules.horizon import vision_intake
from substrate import load_config
from substrate.bus import Bus
from substrate.graph import Graph
from substrate.migrate import migrate


class TextIn(BaseModel):
    text: str


def create_app(cfg: dict | None = None) -> FastAPI:
    cfg = cfg or load_config()
    conn = migrate(cfg)  # idempotent — ensures schema exists
    bus = Bus()
    graph = Graph(conn, bus, default_owner=cfg.get("owner", {}).get("id"))
    claude = ClaudeGateway(cfg)

    app = FastAPI(title="Life OS Gateway", version="0.1.0")
    app.state.cfg = cfg
    app.state.graph = graph
    app.state.claude = claude
    auth = make_auth_dependency(cfg.get("gateway", {}).get("auth_token", ""))

    @app.get("/health")
    def health():
        cur = graph._execute("SELECT COUNT(*) AS n FROM entities")
        row = cur.fetchone()
        n = row["n"] if hasattr(row, "keys") or isinstance(row, dict) else row[0]
        return {"ok": True, "env": cfg.get("env"), "entities": n, "claude": claude.available}

    @app.post("/v1/route", dependencies=[Depends(auth)])
    def route_text(body: TextIn):
        return route(body.text, claude=claude)

    @app.post("/v1/vision", dependencies=[Depends(auth)])
    def vision(body: TextIn):
        return vision_intake.intake(body.text, graph, claude=claude)

    return app
