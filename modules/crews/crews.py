"""Crews — named groups with a topic, a home city, a membership lifecycle and safety rails.

Membership is the grants ACL (same primitive Hearth uses), one row per state:
    crew:admin | crew:member | crew:invited | crew:requested | crew:blocked
State transitions revoke the old grant and add the new one, so a person is only ever in
one state per crew.

Visibility:
    private  — invite-only, never listed in a directory query.
    public   — discoverable (city-level) and joinable by request, subject to admin approval.

Safety is a prerequisite of discovery, not a follow-up: blocking, reporting and leaving
exist here from the start, and a blocked person cannot be invited, request, or be approved.
"""

from substrate import now_iso
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "people:read"}
MODULE = "crews"

ADMIN, MEMBER, INVITED, REQUESTED, BLOCKED = (
    "crew:admin", "crew:member", "crew:invited", "crew:requested", "crew:blocked")
_STATES = (ADMIN, MEMBER, INVITED, REQUESTED, BLOCKED)
VISIBILITIES = ("private", "public")


def _norm(s: str, cap: int = 80) -> str:
    return str(s or "").strip()[:cap]


def _key(s: str) -> str:
    return _norm(s).lower()


def _load(session, crew_id: str) -> dict:
    crew = session.get_entity(crew_id)
    if crew is None or crew["kind"] != "content" or crew["attrs"].get("type") != "crew":
        raise ValueError("unknown crew")
    return crew


def _person(session, person_id: str) -> dict:
    person = session.get_entity(person_id)
    if person is None or person["kind"] != "person":
        raise ValueError("unknown person")
    return person


def _holders(session, crew_id: str, scope: str) -> list[str]:
    return [g["subject"] for g in session.grants_for(crew_id) if g["scope"] == scope]


def _state_of(session, crew_id: str, person_id: str) -> str | None:
    for g in session.grants_for(crew_id):
        if g["subject"] == person_id and g["scope"] in _STATES:
            return g["scope"]
    return None


def _set_state(session, crew_id: str, person_id: str, state: str | None, source: str) -> None:
    """Move a person to exactly one state (or none), revoking any other."""
    for scope in _STATES:
        if scope != state:
            session.revoke(person_id, scope, crew_id, source=source)
    if state and person_id not in _holders(session, crew_id, state):
        session.grant(person_id, state, crew_id, source=source)


def _require_admin(session, crew_id: str, actor_id: str | None, source: str) -> None:
    """Admin-gated action. Crews with no admin at all (simple personal crews) are open to
    their members — we don't lock anyone out of their own group."""
    admins = _holders(session, crew_id, ADMIN)
    if not admins:
        return
    if actor_id not in admins:
        raise ValueError("only a crew admin can do that")


def _names(session, ids: list[str]) -> list[dict]:
    out = []
    for pid in ids:
        person = session.get_entity(pid)
        if person:
            out.append({"id": pid, "name": person["attrs"].get("name", "?")})
    return out


def _view(session, crew: dict) -> dict:
    a = crew["attrs"]
    admins = _holders(session, crew["id"], ADMIN)
    members = sorted(set(_holders(session, crew["id"], MEMBER)) | set(admins))
    return {
        "id": crew["id"], "name": a.get("name", "?"), "topic": a.get("topic", ""),
        "city": a.get("city", ""), "visibility": a.get("visibility", "private"),
        "members": _names(session, members), "member_count": len(members),
        "admins": admins,
        "invited": _names(session, _holders(session, crew["id"], INVITED)),
        "requested": _names(session, _holders(session, crew["id"], REQUESTED)),
        "blocked_count": len(_holders(session, crew["id"], BLOCKED)),
    }


# ---- creation / read --------------------------------------------------------

def create(graph: Graph, name: str, topic: str = "", city: str = "",
           member_ids: list[str] | None = None, visibility: str = "private",
           admin_id: str | None = None, source: str = MODULE) -> dict:
    name, topic, city = _norm(name), _norm(topic, 40), _norm(city, 60)
    if not name:
        raise ValueError("a crew needs a name")
    if visibility not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {VISIBILITIES}")
    session = graph.session(MODULE, SCOPES)
    for existing in session.find_entities("content", {"type": "crew"}, limit=200):
        if _key(existing["attrs"].get("name")) == _key(name):
            raise ValueError(f"crew {name!r} already exists")

    crew_id = session.create_entity("content", {
        "type": "crew", "name": name, "topic": topic, "city": city,
        "visibility": visibility, "created_at": now_iso(),
    }, source=source)
    if admin_id:
        _person(session, admin_id)
        _set_state(session, crew_id, admin_id, ADMIN, source)
    for pid in member_ids or []:
        if pid != admin_id and session.get_entity(pid):
            _set_state(session, crew_id, pid, MEMBER, source)
    return _view(session, _load(session, crew_id))


def get(graph: Graph, crew_id: str) -> dict:
    session = graph.session(MODULE, SCOPES)
    return _view(session, _load(session, crew_id))


def members(graph: Graph, crew_id: str) -> list[str]:
    session = graph.session(MODULE, SCOPES)
    return [m["id"] for m in _view(session, _load(session, crew_id))["members"]]


def browse(graph: Graph, topic: str = "", city: str = "", visibility: str = "",
           limit: int = 50) -> list[dict]:
    """Directory-shaped read: filter by topic/city, and by visibility.

    `visibility="public"` is the DIRECTORY query — the only view a stranger should ever
    get. Default ("") is the local owner's view of their own graph.
    """
    session = graph.session(MODULE, SCOPES)
    out = []
    for crew in session.find_entities("content", {"type": "crew"}, limit=limit):
        a = crew["attrs"]
        if topic and _key(a.get("topic")) != _key(topic):
            continue
        if city and _key(a.get("city")) != _key(city):
            continue
        if visibility and a.get("visibility", "private") != visibility:
            continue
        out.append(_view(session, crew))
    out.sort(key=lambda c: (-c["member_count"], c["name"]))
    return out


def my_crews(graph: Graph, person_id: str) -> list[dict]:
    session = graph.session(MODULE, SCOPES)
    return [_view(session, c) for c in session.find_entities("content", {"type": "crew"}, limit=200)
            if _state_of(session, c["id"], person_id) in (ADMIN, MEMBER)]


# ---- membership lifecycle ---------------------------------------------------

def invite(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
           source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    crew = _load(session, crew_id)
    _person(session, person_id)
    _require_admin(session, crew_id, by, source)
    state = _state_of(session, crew_id, person_id)
    if state == BLOCKED:
        raise ValueError("that person is blocked from this crew")
    if state in (ADMIN, MEMBER):
        return {**_view(session, crew), "invited_now": False}
    _set_state(session, crew_id, person_id, INVITED, source)
    return {**_view(session, _load(session, crew_id)), "invited_now": True}


def accept_invite(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)
    if _state_of(session, crew_id, person_id) != INVITED:
        raise ValueError("no open invite for that person")
    _set_state(session, crew_id, person_id, MEMBER, source)
    return {**_view(session, _load(session, crew_id)), "joined": True}


def decline_invite(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)
    if _state_of(session, crew_id, person_id) != INVITED:
        raise ValueError("no open invite for that person")
    _set_state(session, crew_id, person_id, None, source)
    return {**_view(session, _load(session, crew_id)), "declined": True}


def request_join(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    """Ask to join a PUBLIC crew. Private crews are invite-only, by design."""
    session = graph.session(MODULE, SCOPES)
    crew = _load(session, crew_id)
    _person(session, person_id)
    if crew["attrs"].get("visibility") != "public":
        raise ValueError("this crew is invite-only")
    state = _state_of(session, crew_id, person_id)
    if state == BLOCKED:
        raise ValueError("you can't join that crew")
    if state in (ADMIN, MEMBER):
        return {**_view(session, crew), "requested": False}
    _set_state(session, crew_id, person_id, REQUESTED, source)
    return {**_view(session, _load(session, crew_id)), "requested": True}


def approve_request(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
                    source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)
    _require_admin(session, crew_id, by, source)
    if _state_of(session, crew_id, person_id) != REQUESTED:
        raise ValueError("no open request from that person")
    _set_state(session, crew_id, person_id, MEMBER, source)
    return {**_view(session, _load(session, crew_id)), "approved": person_id}


def deny_request(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
                 source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)
    _require_admin(session, crew_id, by, source)
    if _state_of(session, crew_id, person_id) != REQUESTED:
        raise ValueError("no open request from that person")
    _set_state(session, crew_id, person_id, None, source)
    return {**_view(session, _load(session, crew_id)), "denied": person_id}


def join(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    """Direct add (owner adding someone from their own graph to their own crew)."""
    session = graph.session(MODULE, SCOPES)
    crew = _load(session, crew_id)
    _person(session, person_id)
    state = _state_of(session, crew_id, person_id)
    if state == BLOCKED:
        raise ValueError("that person is blocked from this crew")
    if state in (ADMIN, MEMBER):
        return {**_view(session, crew), "added": False}
    _set_state(session, crew_id, person_id, MEMBER, source)
    return {**_view(session, _load(session, crew_id)), "added": True}


def leave(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    """Anyone can always leave — no approval, no friction."""
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)
    if _state_of(session, crew_id, person_id) not in (ADMIN, MEMBER):
        raise ValueError("not a member of that crew")
    _set_state(session, crew_id, person_id, None, source)
    return {**_view(session, _load(session, crew_id)), "left": True}


# ---- safety -----------------------------------------------------------------

def block(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
          source: str = MODULE) -> dict:
    """Remove someone and stop them coming back. Terminal until unblocked."""
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)
    _person(session, person_id)
    _require_admin(session, crew_id, by, source)
    _set_state(session, crew_id, person_id, BLOCKED, source)
    return {**_view(session, _load(session, crew_id)), "blocked": person_id}


def unblock(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
            source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)
    _require_admin(session, crew_id, by, source)
    if _state_of(session, crew_id, person_id) != BLOCKED:
        raise ValueError("that person isn't blocked")
    _set_state(session, crew_id, person_id, None, source)
    return {**_view(session, _load(session, crew_id)), "unblocked": person_id}


def is_blocked(graph: Graph, crew_id: str, person_id: str) -> bool:
    session = graph.session(MODULE, SCOPES)
    return _state_of(session, crew_id, person_id) == BLOCKED


def report(graph: Graph, crew_id: str, reporter_id: str, reason: str,
           subject_id: str | None = None, source: str = MODULE) -> dict:
    """File a report about a crew or a person in it. Reports are graph entities so they
    are auditable and cannot be silently dropped."""
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)
    reason = _norm(reason, 500)
    if not reason:
        raise ValueError("a report needs a reason")
    report_id = session.create_entity("content", {
        "type": "crew_report", "crew_id": crew_id, "reporter_id": reporter_id,
        "subject_id": subject_id or "", "reason": reason, "status": "open",
        "created_at": now_iso(),
    }, source=source)
    return {"report_id": report_id, "crew_id": crew_id, "status": "open"}


def reports(graph: Graph, crew_id: str = "", status: str = "", limit: int = 100) -> list[dict]:
    session = graph.session(MODULE, SCOPES)
    out = []
    for r in session.find_entities("content", {"type": "crew_report"}, limit=limit):
        a = r["attrs"]
        if crew_id and a.get("crew_id") != crew_id:
            continue
        if status and a.get("status") != status:
            continue
        out.append({"id": r["id"], "crew_id": a.get("crew_id"), "reporter_id": a.get("reporter_id"),
                    "subject_id": a.get("subject_id"), "reason": a.get("reason"),
                    "status": a.get("status"), "created_at": a.get("created_at")})
    return out


def resolve_report(graph: Graph, report_id: str, action: str = "actioned",
                   source: str = MODULE) -> dict:
    if action not in ("actioned", "dismissed"):
        raise ValueError("action must be 'actioned' or 'dismissed'")
    session = graph.session(MODULE, SCOPES)
    rep = session.get_entity(report_id)
    if rep is None or rep["attrs"].get("type") != "crew_report":
        raise ValueError("unknown report")
    session.update_entity(report_id, {"status": action}, source=source)
    return {"report_id": report_id, "status": action}
