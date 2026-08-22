"""Crews — named groups with a topic, a home city, a membership lifecycle and safety rails.

Membership is the grants ACL (same primitive Hearth uses), one row per state:
    crew:admin | crew:member | crew:invited | crew:requested | crew:blocked
State transitions revoke the old grant and add the new one, so a person is only ever in
one state per crew.

Two orthogonal knobs the admin controls:

    visibility  private — never listed in a directory query.
                public  — discoverable (city-level).

    admission   invite   — invites only; requests are refused.
                approval — anyone may request; an admin admits them (default).
                open     — a request admits instantly (a drop-in crew).

Private crews are always invite-only: something unlisted can't be requested.

Safety is a prerequisite of discovery, not a follow-up: blocking, reporting and leaving
exist here from the start, and a blocked person cannot be invited, request, or be approved.
"""

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "people:read"}
MODULE = "crews"

ADMIN, MEMBER, INVITED, REQUESTED, BLOCKED = (
    "crew:admin", "crew:member", "crew:invited", "crew:requested", "crew:blocked")
_STATES = (ADMIN, MEMBER, INVITED, REQUESTED, BLOCKED)
VISIBILITIES = ("private", "public")
ADMISSIONS = ("invite", "approval", "open")


def _effective_admission(attrs: dict) -> str:
    """Private crews are invite-only regardless of what's stored."""
    if attrs.get("visibility", "private") != "public":
        return "invite"
    return attrs.get("admission", "approval")


def _norm(s: str, cap: int = 80) -> str:
    return str(s or "").strip()[:cap]


def _key(s: str) -> str:
    return _norm(s).lower()


def _load(session, crew_id: str) -> dict:
    crew = session.get_entity(crew_id)
    if crew is None or crew["kind"] != "content" or crew["attrs"].get("type") != "crew":
        raise ValueError("unknown crew")
    return crew


def _load_visible(session, crew_id: str, subject: str | None = None) -> tuple[dict, bool]:
    """A crew you own, one you BELONG to, or someone else's PUBLISHED one.

    Returns (crew, is_mine); `is_mine` then decides how strict the admin rules are.

    Three routes because there are three genuinely different reasons to be allowed to read
    a crew, and the middle one is easy to forget: **membership itself confers read access.**
    Invite links made private cross-account crews possible, and without this a member of one
    could not see the very group they had just joined — the crew is in nobody's public
    listing and not in their graph. The membership grant is the permission, exactly as it is
    for a shared planning session.
    """
    crew = session.get_entity(crew_id)
    if crew is not None and crew["attrs"].get("type") == "crew":
        return crew, True
    if subject:
        crew = session.get_if_granted(crew_id, subject, {ADMIN, MEMBER, INVITED})
        if crew is not None and crew["kind"] == "content" and crew["attrs"].get("type") == "crew":
            return crew, False
    crew = session.get_public(crew_id)
    if crew is None or crew["kind"] != "content" or crew["attrs"].get("type") != "crew":
        raise ValueError("unknown crew")
    return crew, False



def _account_handle(session, subject_id: str) -> str | None:
    """Resolve a member subject that is an ACCOUNT rather than a local person.

    Only the handle is read — never anything else on the account record.
    """
    system = Graph(session.graph.conn, session.graph.bus, default_owner=SYSTEM_OWNER)
    account = system.session(MODULE, {"content:read"}).get_entity(subject_id)
    if account is None or account["attrs"].get("type") != "account":
        return None
    return account["attrs"].get("handle")


def _subject_exists(session, subject_id: str) -> bool:
    """A member subject is either a person in YOUR graph or an account in the system.

    Two different things are deliberately kept apart: `person` is your own private record
    of someone you know, and stays local; an ACCOUNT is who someone is across the system,
    and is what shared crews are built from.
    """
    local = session.get_entity(subject_id) if subject_id else None
    if local is not None and local["kind"] == "person":
        return True
    return _account_handle(session, subject_id) is not None


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
    if state and person_id not in _holders(session, crew_id, state):
        session.grant(person_id, state, crew_id, source=source)
    for scope in _STATES:
        if scope != state:
            session.revoke(person_id, scope, crew_id, source=source)


def _require_admin(session, crew_id: str, actor_id: str | None, source: str,
                   is_mine: bool = True) -> None:
    """Admin-gated action.

    A crew of your own with no admin at all (a simple personal crew) stays open to its
    members — nobody should be locked out of their own group. That leniency must NOT
    extend to someone else's crew, or an adminless public crew would be adminable by any
    passer-by.
    """
    admins = _holders(session, crew_id, ADMIN)
    if not admins:
        if is_mine:
            return
        raise ValueError("only a crew admin can do that")
    if actor_id not in admins:
        raise ValueError("only a crew admin can do that")


def _names(session, ids: list[str]) -> list[dict]:
    """Resolve member subjects for display.

    A local person gives their name; an account gives its handle. A subject that is
    neither — someone else's person, in someone else's graph — is omitted, which is why
    another account's crew shows its size but not its roster.
    """
    out = []
    for sid in ids:
        person = session.get_entity(sid)
        if person is not None and person["kind"] == "person":
            out.append({"id": sid, "name": person["attrs"].get("name", "?")})
            continue
        handle = _account_handle(session, sid)
        if handle:
            out.append({"id": sid, "name": handle, "account": True})
    return out


def _reload_view(session, crew_id: str, subject: str | None = None) -> dict:
    """Re-read for the response after a state change — works for someone else's published
    crew, and for a private one you're a member of, so a successful cross-account join
    doesn't fail on the way back out."""
    crew, _ = _load_visible(session, crew_id, subject)
    return _view(session, crew)


def _view(session, crew: dict) -> dict:
    a = crew["attrs"]
    admins = _holders(session, crew["id"], ADMIN)
    members = sorted(set(_holders(session, crew["id"], MEMBER)) | set(admins))
    return {
        "id": crew["id"], "name": a.get("name", "?"), "topic": a.get("topic", ""),
        "city": a.get("city", ""), "visibility": a.get("visibility", "private"),
        "admission": _effective_admission(a),
        "members": _names(session, members), "member_count": len(members),
        "admins": admins,
        "invited": _names(session, _holders(session, crew["id"], INVITED)),
        "requested": _names(session, _holders(session, crew["id"], REQUESTED)),
        "blocked_count": len(_holders(session, crew["id"], BLOCKED)),
    }


# ---- creation / read --------------------------------------------------------

def create(graph: Graph, name: str, topic: str = "", city: str = "",
           member_ids: list[str] | None = None, visibility: str = "private",
           admin_id: str | None = None, admission: str = "approval",
           source: str = MODULE) -> dict:
    name, topic, city = _norm(name), _norm(topic, 40), _norm(city, 60)
    if not name:
        raise ValueError("a crew needs a name")
    if visibility not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {VISIBILITIES}")
    if admission not in ADMISSIONS:
        raise ValueError(f"admission must be one of {ADMISSIONS}")
    session = graph.session(MODULE, SCOPES)
    for existing in session.find_entities("content", {"type": "crew"}, limit=200):
        if _key(existing["attrs"].get("name")) == _key(name):
            raise ValueError(f"crew {name!r} already exists")

    crew_id = session.create_entity("content", {
        "type": "crew", "name": name, "topic": topic, "city": city,
        "visibility": visibility, "admission": admission, "created_at": now_iso(),
    }, source=source)
    if admin_id:
        # The admin may be a local person (a personal crew) or an ACCOUNT (a shared one).
        if not _subject_exists(session, admin_id):
            raise ValueError("unknown person")
        _set_state(session, crew_id, admin_id, ADMIN, source)
    for pid in member_ids or []:
        if pid != admin_id and _subject_exists(session, pid):
            _set_state(session, crew_id, pid, MEMBER, source)
    return _reload_view(session, crew_id)


def get(graph: Graph, crew_id: str, subject: str | None = None) -> dict:
    """`subject` is the caller's identity — it is what makes a private crew readable by
    its own members, and is ignored for crews you own or that were published."""
    session = graph.session(MODULE, SCOPES)
    return _reload_view(session, crew_id, subject)


def members(graph: Graph, crew_id: str, subject: str | None = None) -> list[str]:
    session = graph.session(MODULE, SCOPES)
    return [m["id"] for m in _reload_view(session, crew_id, subject)["members"]]


def browse(graph: Graph, topic: str = "", city: str = "", visibility: str = "",
           limit: int = 50, across_users: bool = False) -> list[dict]:
    """Directory-shaped read: filter by topic/city, and by visibility.

    Default is the owner's own view of their own crews. `across_users=True` is the real
    DIRECTORY — it spans accounts and, by construction, can only ever return crews their
    admins explicitly published.
    """
    session = graph.session(MODULE, SCOPES)
    if across_users:
        crews_found = session.find_public("content", {"type": "crew"}, limit=limit)
    else:
        crews_found = session.find_entities("content", {"type": "crew"}, limit=limit)
        if visibility:
            crews_found = [c for c in crews_found
                           if c["attrs"].get("visibility", "private") == visibility]
    out = []
    for crew in crews_found:
        a = crew["attrs"]
        if topic and _key(a.get("topic")) != _key(topic):
            continue
        if city and _key(a.get("city")) != _key(city):
            continue
        out.append(_view(session, crew))
    out.sort(key=lambda c: (-c["member_count"], c["name"]))
    return out


def directory(graph: Graph, topic: str = "", city: str = "", limit: int = 50) -> list[dict]:
    """The public crew directory: every published crew, whoever owns it. Land in a new
    city, see who's climbing there."""
    return browse(graph, topic=topic, city=city, limit=limit, across_users=True)


def my_crews(graph: Graph, person_id: str) -> list[dict]:
    """Every crew you belong to — your own, plus published ones you've joined elsewhere.

    Membership lives in the ACL, not in your graph, so a crew you joined in someone else's
    account would otherwise be invisible to you despite your being in it.
    """
    session = graph.session(MODULE, SCOPES)
    seen, out = set(), []
    for crew in (session.find_entities("content", {"type": "crew"}, limit=200)
                 + session.find_public("content", {"type": "crew"}, limit=200)):
        if crew["id"] in seen:
            continue
        seen.add(crew["id"])
        if _state_of(session, crew["id"], person_id) in (ADMIN, MEMBER):
            out.append(_view(session, crew))
    # A PRIVATE crew you joined by invite link is in neither list — not yours, never
    # published — so the grants you hold are the only index that can find it.
    for crew_id in session.spaces_granted(person_id, {ADMIN, MEMBER}):
        if crew_id in seen:
            continue
        seen.add(crew_id)
        crew = session.get_if_granted(crew_id, person_id, {ADMIN, MEMBER})
        if crew is not None and crew["kind"] == "content" and crew["attrs"].get("type") == "crew":
            out.append(_view(session, crew))
    return out


# ---- membership lifecycle ---------------------------------------------------

def invite(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
           source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    crew, mine = _load_visible(session, crew_id, by)
    if not _subject_exists(session, person_id):
        raise ValueError("unknown person")
    _require_admin(session, crew_id, by, source, mine)
    state = _state_of(session, crew_id, person_id)
    if state == BLOCKED:
        raise ValueError("that person is blocked from this crew")
    if state in (ADMIN, MEMBER):
        return {**_view(session, crew), "invited_now": False}
    _set_state(session, crew_id, person_id, INVITED, source)
    return {**_reload_view(session, crew_id, by), "invited_now": True}


def accept_invite(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _load_visible(session, crew_id, person_id)
    if _state_of(session, crew_id, person_id) != INVITED:
        raise ValueError("no open invite for that person")
    _set_state(session, crew_id, person_id, MEMBER, source)
    return {**_reload_view(session, crew_id, person_id), "joined": True}


def decline_invite(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _load_visible(session, crew_id, person_id)
    if _state_of(session, crew_id, person_id) != INVITED:
        raise ValueError("no open invite for that person")
    _set_state(session, crew_id, person_id, None, source)
    return {**_reload_view(session, crew_id), "declined": True}



def request_join(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    """Ask to join — including someone else's published crew, as your account.

    This is the one write that reaches across accounts, and it is deliberately the
    narrowest one possible: it can only ever put YOU into `requested` (or `member`, when
    the admin has declared the crew open), it touches the ACL and never the owner's
    entities, and it cannot grant admin. The crew's admission policy decides:
    invite -> refused, approval -> queued for an admin, open -> admitted on the spot.
    """
    session = graph.session(MODULE, SCOPES)
    crew, _mine = _load_visible(session, crew_id, person_id)
    if not _subject_exists(session, person_id):
        raise ValueError("unknown person")
    admission = _effective_admission(crew["attrs"])
    if admission == "invite":
        raise ValueError("this crew is invite-only")
    state = _state_of(session, crew_id, person_id)
    if state == BLOCKED:
        raise ValueError("you can't join that crew")
    if state in (ADMIN, MEMBER):
        return {**_view(session, crew), "requested": False, "joined": False}

    if admission == "open":
        _set_state(session, crew_id, person_id, MEMBER, source)
        return {**_reload_view(session, crew_id, person_id), "requested": False, "joined": True}
    _set_state(session, crew_id, person_id, REQUESTED, source)
    return {**_reload_view(session, crew_id, person_id), "requested": True, "joined": False}


def set_policy(graph: Graph, crew_id: str, visibility: str | None = None,
               admission: str | None = None, by: str | None = None,
               source: str = MODULE) -> dict:
    """Admin control over how the crew is found and who gets in."""
    session = graph.session(MODULE, SCOPES)
    _load(session, crew_id)                  # policy changes only on a crew you own
    _require_admin(session, crew_id, by, source)
    patch = {}
    if visibility is not None:
        if visibility not in VISIBILITIES:
            raise ValueError(f"visibility must be one of {VISIBILITIES}")
        patch["visibility"] = visibility
    if admission is not None:
        if admission not in ADMISSIONS:
            raise ValueError(f"admission must be one of {ADMISSIONS}")
        patch["admission"] = admission
    if patch:
        session.update_entity(crew_id, patch, source=source)
    return _reload_view(session, crew_id)


def approve_request(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
                    source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _, mine = _load_visible(session, crew_id, by)
    _require_admin(session, crew_id, by, source, mine)
    if _state_of(session, crew_id, person_id) != REQUESTED:
        raise ValueError("no open request from that person")
    _set_state(session, crew_id, person_id, MEMBER, source)
    return {**_reload_view(session, crew_id, by), "approved": person_id}


def deny_request(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
                 source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _, mine = _load_visible(session, crew_id, by)
    _require_admin(session, crew_id, by, source, mine)
    if _state_of(session, crew_id, person_id) != REQUESTED:
        raise ValueError("no open request from that person")
    _set_state(session, crew_id, person_id, None, source)
    return {**_reload_view(session, crew_id, by), "denied": person_id}


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
    return {**_reload_view(session, crew_id), "added": True}


def leave(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    """Anyone can always leave — no approval, no friction."""
    session = graph.session(MODULE, SCOPES)
    crew, _ = _load_visible(session, crew_id, person_id)   # walk out of someone else's crew too
    if _state_of(session, crew_id, person_id) not in (ADMIN, MEMBER):
        raise ValueError("not a member of that crew")
    _set_state(session, crew_id, person_id, None, source)
    # Rendered from the crew read on the way IN: leaving is exactly what removes your right
    # to read it again, so re-fetching here would make a successful exit throw. `_view` still
    # re-reads the grants, so the roster it returns is the post-departure one.
    return {**_view(session, crew), "left": True}


# ---- safety -----------------------------------------------------------------

def block(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
          source: str = MODULE) -> dict:
    """Remove someone and stop them coming back. Terminal until unblocked."""
    session = graph.session(MODULE, SCOPES)
    _, mine = _load_visible(session, crew_id, by)
    if not _subject_exists(session, person_id):
        raise ValueError("unknown person")
    _require_admin(session, crew_id, by, source, mine)
    _set_state(session, crew_id, person_id, BLOCKED, source)
    return {**_reload_view(session, crew_id, by), "blocked": person_id}


def unblock(graph: Graph, crew_id: str, person_id: str, by: str | None = None,
            source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    _, mine = _load_visible(session, crew_id, by)
    _require_admin(session, crew_id, by, source, mine)
    if _state_of(session, crew_id, person_id) != BLOCKED:
        raise ValueError("that person isn't blocked")
    _set_state(session, crew_id, person_id, None, source)
    return {**_reload_view(session, crew_id, by), "unblocked": person_id}


def is_blocked(graph: Graph, crew_id: str, person_id: str) -> bool:
    session = graph.session(MODULE, SCOPES)
    return _state_of(session, crew_id, person_id) == BLOCKED


def is_member(graph: Graph, crew_id: str, person_id: str) -> bool:
    """Whether this person is in this crew, admins included.

    The membership test for crew-scoped objects that are not the crew itself — polls and
    beacons — so the rule lives in one place rather than being re-derived, slightly
    differently, next to each new thing that needs it. Blocked is not a member.
    """
    if not (crew_id and person_id):
        return False
    session = graph.session(MODULE, SCOPES)
    return _state_of(session, crew_id, person_id) in (ADMIN, MEMBER)


def is_admin(graph: Graph, crew_id: str, person_id: str) -> bool:
    """Whether this person administers this crew.

    The public form of the admin test, so a crew-scoped feature does not have to reach into
    `_require_admin` and guess at its `is_mine` argument — which means "the crew lives in
    your own graph", not "you are in it", and is exactly the kind of thing that gets passed
    `True` by a caller who wanted the second meaning.
    """
    if not (crew_id and person_id):
        return False
    session = graph.session(MODULE, SCOPES)
    return _state_of(session, crew_id, person_id) == ADMIN


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
