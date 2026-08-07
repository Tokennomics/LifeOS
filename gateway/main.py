"""Life OS gateway — FastAPI app + the mobile app it serves.

Run:  .venv\\Scripts\\uvicorn gateway.main:create_app --factory --port 8787
The PWA lives at /app/ (surfaces/app/www). All endpoints work without any API keys
(deterministic offline fallbacks); ANTHROPIC_API_KEY upgrades them in place.
"""

import datetime
import json
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gateway import accounts, rate_limiter
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

#: Generous for a note or an ICS import, nowhere near enough to fill a disk with.
MAX_BODY_BYTES = 1_000_000


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


class ErasureIn(BaseModel):
    password: str
    confirm: str = ""


class OidcSignInIn(BaseModel):
    provider: str
    id_token: str
    nonce: str = ""


class LinkIdentityIn(BaseModel):
    provider: str
    subject: str = ""
    id_token: str = ""
    nonce: str = ""


def _g(request: Request) -> Graph:
    """The caller's own slice of the graph (config owner when there are no accounts)."""
    return caller_graph(request)


def _count(graph: Graph, sql: str, params: tuple = ()) -> int:
    row = graph._execute(sql, params).fetchone()
    return row["n"] if hasattr(row, "keys") or isinstance(row, dict) else row[0]


# `edges` and `observations` carry no owner_id and the v0 schema is final, so the owner
# boundary has to be reconstructed by joining back to entities. Both helpers return
# ("", ()) for an unscoped caller (the single-user config-owner install), which is the
# original behaviour and correct there — there is only one owner.

_OWNED = "SELECT id FROM entities WHERE owner_id = ?"


def _edges_scope(owner: str | None) -> tuple[str, tuple]:
    """An edge belongs to you if either end does. A dangling edge to someone else's entity
    is still part of your graph and must survive the export."""
    if not owner:
        return "", ()
    return f"WHERE src IN ({_OWNED}) OR dst IN ({_OWNED})", (owner, owner)


def _observations_scope(owner: str | None) -> tuple[str, tuple]:
    if not owner:
        return "", ()
    return f"WHERE entity_id IN ({_OWNED})", (owner,)


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


SEED_CITY_VAR = "LIFEOS_SEED_CITY"


def _seed_on_boot(graph: Graph) -> dict:
    """Load a committed city pack the first time this instance starts.

    An empty app is the thing that loses a new user in the first ten seconds, and asking
    someone to paste twenty venue websites before they can see a weekend is not an onboarding
    flow. `LIFEOS_SEED_CITY=lisbon` loads `seeds/lisbon.json` once.

    Deliberately quiet and deliberately non-fatal: it subscribes to feeds and does NOT fetch
    them (a boot that waits on twenty venue servers is a boot that fails a health check), and
    any error is swallowed — a bad pack must never stop the gateway from starting. Re-running
    is a no-op because `add_feed` is idempotent on the URL.
    """
    city = str(os.environ.get(SEED_CITY_VAR, "")).strip()
    if not city:
        return {"seeded": False}
    try:
        from modules.feeds import seeds
        result = seeds.apply(graph, city, sync=False, resolve=False)
        print(f"[seed] {city}: {len(result['added'])} feeds added, "
              f"{len(result['already_had'])} already there, {len(result['failed'])} failed")
        return {"seeded": True, **result}
    except Exception as exc:                    # never block a boot on seed data
        print(f"[seed] {city}: skipped ({type(exc).__name__}: {exc})")
        return {"seeded": False, "error": str(exc)}


def create_app(cfg: dict | None = None) -> FastAPI:
    cfg = cfg or load_config()
    conn = migrate(cfg)  # idempotent — ensures schema exists
    bus = Bus()
    graph = Graph(conn, bus, default_owner=cfg.get("owner", {}).get("id"))
    claude = ClaudeGateway(cfg)

    app = FastAPI(title="Life OS Gateway", version="0.2.0")
    # The Capacitor app runs from capacitor:// and the PWA is served same-origin, so auth
    # stays on the bearer token and `*` is workable — a cross-origin caller still needs a
    # token, and tokens are never cookies. It is still wider than a public box wants, so
    # `gateway.cors_origins` narrows it without a code change; `*` remains the default only
    # because tightening it silently would break an installed app mid-trip.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.get("gateway", {}).get("cors_origins") or ["*"],
        allow_methods=["*"], allow_headers=["*"],
    )
    # One cap for every endpoint, rather than a length check per field. A signed-up user
    # could otherwise store an unbounded blob per request and fill the disk — which on a
    # small hosted box takes down everyone's instance, not just their own. Found by probing
    # with a 2MB capture, which was accepted and stored whole.
    max_body = int(cfg.get("gateway", {}).get("max_body_bytes") or MAX_BODY_BYTES)

    @app.middleware("http")
    async def _limit_body(request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_body:
            return JSONResponse(status_code=413,
                                content={"detail": f"body larger than {max_body} bytes"})
        return await call_next(request)

    app.state.cfg = cfg
    app.state.rate_limiter = rate_limiter.RateLimiter()
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

    _seed_on_boot(graph)

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
    def auth_register(request: Request, body: CredentialsIn):
        """Open signup, but not unlimited: these two routes are the only ones reachable
        without a token, so they are the whole unauthenticated attack surface."""
        rate_limiter.enforce(request, "auth:register", max_requests=5, window_seconds=3600)
        try:
            return accounts.register(graph, body.handle, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/v1/auth/login")
    def auth_login(request: Request, body: CredentialsIn):
        """Rate-limited because PBKDF2 alone is not a lockout — 200k iterations makes each
        guess cost ~100ms, which still allows tens of thousands of guesses a day."""
        rate_limiter.enforce(request, "auth:login", max_requests=10, window_seconds=300)
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

    # ---- Ways in: password, Google, Apple, email, phone -------------------

    @app.get("/v1/auth/providers")
    def auth_providers():
        """Which sign-in methods this deployment offers.

        **Unauthenticated on purpose, and it was briefly not.** It lived on the authed
        router, which meant a client had to already be signed in to discover how to sign
        in — the sign-in screen could not render. Found by walking the product as a new
        user, not by a test. Configuration only: never a client id.
        """
        from modules.auth import oidc
        return {"providers": oidc.status(), "password": True}

    @app.post("/v1/auth/oidc")
    def auth_oidc(request: Request, body: OidcSignInIn):
        """Sign in with an ID token from Google or Apple.

        A new identity makes a NEW account, even when the email matches an existing one —
        auto-linking by email is the classic takeover and `gateway/identities.py` says why
        at length. To connect a second way in, use /v1/auth/identities while signed in.
        """
        from modules.auth import oidc
        from gateway import identities
        rate_limiter.enforce(request, "auth:oidc", max_requests=20, window_seconds=300)
        try:
            proof = oidc.verify_id_token(body.provider, body.id_token, nonce=body.nonce or None)
        except oidc.TokenRejected as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        return identities.sign_in(graph, proof["provider"], proof["subject"],
                                  handle_hint=proof["email"].split("@")[0] if proof["email"] else "")

    @app.get("/v1/auth/identities", dependencies=[Depends(auth)])
    def auth_identities(request: Request):
        from gateway import identities
        caller = getattr(request.state, "caller", None)
        if not caller:
            raise HTTPException(status_code=400, detail="sign in with an account first")
        return {"identities": identities.for_account(graph, caller["account_id"])}

    @app.post("/v1/auth/identities", dependencies=[Depends(auth)])
    def auth_link_identity(request: Request, body: LinkIdentityIn):
        """Connect another way in to the account you are signed in to — the only moment
        both sides are known, which is why linking happens here and nowhere else."""
        from modules.auth import oidc
        from gateway import identities
        caller = getattr(request.state, "caller", None)
        if not caller:
            raise HTTPException(status_code=400, detail="sign in with an account first")
        subject = body.subject
        if body.id_token:
            try:
                subject = oidc.verify_id_token(body.provider, body.id_token,
                                               nonce=body.nonce or None)["subject"]
            except oidc.TokenRejected as exc:
                raise HTTPException(status_code=401, detail=str(exc))
        try:
            return identities.link(graph, caller["account_id"], body.provider, subject)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete("/v1/auth/identities", dependencies=[Depends(auth)])
    def auth_unlink_identity(request: Request, body: LinkIdentityIn):
        from gateway import identities
        caller = getattr(request.state, "caller", None)
        if not caller:
            raise HTTPException(status_code=400, detail="sign in with an account first")
        try:
            return identities.unlink(graph, caller["account_id"], body.provider, body.subject)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ---- Your data is yours: see it, take it, delete it -------------------

    @app.get("/v1/auth/account/erase-preview", dependencies=[Depends(auth)])
    def erase_preview(request: Request):
        """What deleting would remove. Shown before the button, never after."""
        from modules.privacy import erasure
        caller = getattr(request.state, "caller", None)
        if not caller:
            raise HTTPException(status_code=400, detail="sign in with an account first")
        return erasure.preview(graph, caller["account_id"], caller["owner_id"])

    @app.post("/v1/auth/account/erase", dependencies=[Depends(auth)])
    def erase_account(request: Request, body: ErasureIn):
        """Delete this account and everything belonging to it. Irreversible.

        The password is required again even though the caller already holds a valid token:
        a stolen or borrowed phone should not be able to erase someone's life, and this is
        the one action with no undo. `confirm` must be the literal handle, which is the
        oldest and best guard against a mis-tap.
        """
        from modules.privacy import erasure
        caller = getattr(request.state, "caller", None)
        if not caller:
            raise HTTPException(status_code=400, detail="sign in with an account first")
        rate_limiter.enforce(request, "auth:erase", max_requests=5, window_seconds=3600)
        try:
            accounts.login(graph, caller["handle"], body.password, ttl_hours=1)
        except ValueError:
            raise HTTPException(status_code=401, detail="password does not match")
        if body.confirm.strip() != caller["handle"]:
            raise HTTPException(
                status_code=400,
                detail=f"type your handle ({caller['handle']}) in `confirm` to erase")
        return erasure.erase_account(graph, caller["account_id"], caller["owner_id"])

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
        edge_sql, edge_params = _edges_scope(owner)
        obs_sql, obs_params = _observations_scope(owner)
        return {"entities": sum(counts.values()), "counts": counts,
                "edges": _count(scoped, f"SELECT COUNT(*) AS n FROM edges {edge_sql}", edge_params),
                "observations": _count(
                    scoped, f"SELECT COUNT(*) AS n FROM observations {obs_sql}", obs_params),
                "recent": recent}

    @app.get("/v1/export", dependencies=[Depends(auth)])
    def export(request: Request):
        """Law 2: full export always. The graph is the user's — and ONLY the user's.

        `entities` was owner-filtered here and `edges`/`observations` were not, so every
        account's export carried every other account's edge list and the provenance row for
        every write in the database: entity ids, which module wrote them, and when. Not
        content, but a complete activity timeline for every user on the box. Neither table
        has an `owner_id` column and the v0 schema is final, so both are scoped by joining
        back to the entities the caller actually owns.
        """
        scoped = _g(request)
        owner = scoped.default_owner

        def rows(table):
            if not owner:
                return [dict(r) for r in scoped._execute(f"SELECT * FROM {table}").fetchall()]
            if table == "entities":
                return [dict(r) for r in scoped._execute(
                    "SELECT * FROM entities WHERE owner_id = ?", (owner,)).fetchall()]
            where, params = (_edges_scope(owner) if table == "edges"
                             else _observations_scope(owner))
            return [dict(r) for r in scoped._execute(
                f"SELECT * FROM {table} {where}", params).fetchall()]
        entities = rows("entities")
        for e in entities:
            e["attrs"] = json.loads(e["attrs"]) if isinstance(e["attrs"], str) else e["attrs"]
            e.pop("embedding", None)
        edges = rows("edges")
        for e in edges:
            e["attrs"] = json.loads(e["attrs"]) if isinstance(e["attrs"], str) else e["attrs"]
        return {"exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "entities": entities, "edges": edges, "observations": rows("observations")}

    # ---- Crew Invite Landing Page ----------------------------------------

    EXPIRED_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Invalid Invite - LifeOS</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        body {
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #0a0a0c 0%, #121218 100%);
            color: #e2e8f0;
            font-family: 'Outfit', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        .card {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 24px;
            padding: 40px;
            text-align: center;
            max-width: 400px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
            animation: fadeIn 0.6s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        h1 {
            color: #ef4444;
            font-size: 28px;
            margin-bottom: 16px;
            font-weight: 700;
        }
        p {
            color: #94a3b8;
            font-size: 16px;
            line-height: 1.6;
            margin-bottom: 24px;
        }
        .btn {
            display: inline-block;
            background: rgba(255, 255, 255, 0.08);
            color: #f8fafc;
            text-decoration: none;
            padding: 14px 28px;
            border-radius: 12px;
            font-weight: 600;
            transition: all 0.3s ease;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .btn:hover {
            background: rgba(255, 255, 255, 0.15);
            border-color: rgba(255, 255, 255, 0.2);
            transform: translateY(-2px);
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>Invite Link Expired</h1>
        <p>This invite link is either invalid, revoked, or has reached its maximum usage limit. Ask the crew administrator for a new invite link.</p>
        <a href="/app/" class="btn">Go to LifeOS</a>
    </div>
</body>
</html>
"""

    INVITE_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Crew Invitation - LifeOS</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #09090b 0%, #151522 100%);
            color: #f4f4f5;
            font-family: 'Outfit', sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            overflow: hidden;
            position: relative;
        }}
        .bg-glow {{
            position: absolute;
            width: 300px;
            height: 300px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(99, 102, 241, 0.15) 0%, rgba(0,0,0,0) 70%);
            top: 20%;
            left: 30%;
            z-index: 0;
            filter: blur(40px);
        }}
        .bg-glow-2 {{
            position: absolute;
            width: 400px;
            height: 400px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(236, 72, 153, 0.1) 0%, rgba(0,0,0,0) 70%);
            bottom: 10%;
            right: 20%;
            z-index: 0;
            filter: blur(50px);
        }}
        .card {{
            position: relative;
            background: rgba(30, 30, 40, 0.45);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 32px;
            padding: 48px;
            text-align: center;
            max-width: 450px;
            width: 90%;
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.4);
            z-index: 10;
            animation: cardEntrance 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }}
        @keyframes cardEntrance {{
            from {{ opacity: 0; transform: translateY(30px) scale(0.96); }}
            to {{ opacity: 1; transform: translateY(0) scale(1); }}
        }}
        .logo {{
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 4px;
            color: #a1a1aa;
            margin-bottom: 32px;
            font-weight: 700;
        }}
        .logo span {{
            background: linear-gradient(90deg, #6366f1, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        h1 {{
            font-size: 26px;
            margin-bottom: 8px;
            font-weight: 600;
            color: #ffffff;
        }}
        .crew-name {{
            font-size: 36px;
            font-weight: 700;
            margin: 16px 0 24px 0;
            background: linear-gradient(90deg, #818cf8, #f472b6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        p {{
            color: #a1a1aa;
            font-size: 16px;
            line-height: 1.6;
            margin-bottom: 40px;
        }}
        .btn {{
            display: block;
            background: linear-gradient(90deg, #4f46e5 0%, #db2777 100%);
            color: #ffffff;
            text-decoration: none;
            padding: 18px;
            border-radius: 16px;
            font-weight: 700;
            font-size: 18px;
            box-shadow: 0 10px 25px rgba(79, 70, 229, 0.35);
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .btn:hover {{
            transform: translateY(-3px);
            box-shadow: 0 15px 35px rgba(79, 70, 229, 0.5);
            border-color: rgba(255, 255, 255, 0.2);
        }}
        .btn:active {{
            transform: translateY(-1px);
        }}
    </style>
</head>
<body>
    <div class="bg-glow"></div>
    <div class="bg-glow-2"></div>
    <div class="card">
        <div class="logo">Life<span>OS</span></div>
        <h1>You've been invited to</h1>
        <div class="crew-name">{crew_name}</div>
        <p>Connect with members, share memories, plan itineraries, and coordinate outing slots with ease.</p>
        <a href="/app/?invite_token={token}" class="btn">Join Crew</a>
    </div>
</body>
</html>
"""

    @app.get("/invite/{token}", include_in_schema=False)
    def render_invite_landing(token: str):
        from modules.crews import invites
        from substrate.graph import Graph
        from substrate import SYSTEM_OWNER
        
        sys_graph = Graph(graph.conn, bus, default_owner=SYSTEM_OWNER)
        session = sys_graph.session(invites.MODULE, invites.SCOPES)
        invite = invites._resolve(session, token)
        
        if invite is None or not invites._is_active(invite["attrs"]):
            return Response(content=EXPIRED_HTML, media_type="text/html")
            
        crew_name = invite["attrs"].get("crew_name", "a private crew")
        html_content = INVITE_HTML.format(crew_name=crew_name, token=token)
        return Response(content=html_content, media_type="text/html")

    # ---- the app itself --------------------------------------------------

    if APP_DIR.exists():
        app.mount("/app", StaticFiles(directory=str(APP_DIR), html=True), name="app")

        @app.get("/", include_in_schema=False)
        def index():
            return RedirectResponse("/app/")

    return app
