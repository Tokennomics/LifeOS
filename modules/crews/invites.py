"""Crew invite links — the way a group that already exists becomes a crew.

The public directory only helps where there are already people; a link works from zero.
Paste it into the group chat you're already in and the whole group is a crew — no
directory, no strangers, no waiting for density. That makes this the one growth mechanic
that functions before the network exists (see `docs/GROWTH.md`).

**A link is a capability, so it is held to the same discipline as a session token:**

- 256 random bits, and **only the SHA-256 is stored** — reading the database cannot
  reconstruct a working link, and the token is shown exactly once, at creation.
- **Bounded by default, in two independent ways**: it expires (7 days) *and* it is
  use-limited (25). A link that leaks stops being useful on its own, without anyone
  noticing and intervening.
- **Revocable**, immediately, by an admin — the standing rule for every capability here.
- **It can never confer `admin`,** only `member`. An admin invites people to the crew, not
  to their own privileges.
- **A block still wins.** Someone barred from a crew cannot walk back in through a link,
  which is the obvious hole in any share-link design and the one that matters for safety.

Invites live under `SYSTEM_OWNER`, the same slice accounts and sessions use. That is what
lets someone in another account redeem one: they hold the secret, and the record they're
allowed to find with it belongs to no user's personal graph.
"""

import datetime
import hashlib
import secrets

from modules.crews import crews
from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "people:read"}
MODULE = "crew_invites"

TOKEN_BYTES = 32
DEFAULT_TTL_HOURS = 24 * 7
DEFAULT_MAX_USES = 25
MAX_TTL_HOURS = 24 * 90


def _sys(graph: Graph):
    """A session over the system-owned slice — where capability records live, so that a
    holder in any account can resolve one without reaching into anyone's personal graph."""
    system = Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER)
    return system.session(MODULE, SCOPES)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expiry(ttl_hours: int) -> str:
    hours = max(1, min(int(ttl_hours or DEFAULT_TTL_HOURS), MAX_TTL_HOURS))
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=hours)).isoformat()


def _view(invite: dict) -> dict:
    """Never includes the token or its hash — there is no way to re-read a link."""
    a = invite["attrs"]
    return {"invite_id": invite["id"], "crew_id": a.get("crew_id"),
            "created_at": a.get("created_at"), "expires_at": a.get("expires_at"),
            "max_uses": a.get("max_uses"), "uses": a.get("uses", 0),
            "revoked": bool(a.get("revoked")), "active": _is_active(a)}


def _is_active(a: dict) -> bool:
    if a.get("revoked"):
        return False
    if a.get("expires_at") and a["expires_at"] < now_iso():
        return False
    max_uses = a.get("max_uses") or 0
    return not (max_uses and a.get("uses", 0) >= max_uses)


def create(graph: Graph, crew_id: str, by: str | None = None, ttl_hours: int = DEFAULT_TTL_HOURS,
           max_uses: int = DEFAULT_MAX_USES, source: str = MODULE) -> dict:
    """Mint a link for a crew you administer. The token is returned ONCE and never again."""
    crew_session = graph.session(MODULE, crews.SCOPES)
    # `by` is passed so a MEMBER of a private crew gets the accurate "only an admin can do
    # that" rather than "unknown crew"; a non-member still just sees a crew that isn't there.
    crew, mine = crews._load_visible(crew_session, crew_id, by)
    crews._require_admin(crew_session, crew_id, by, source, mine)

    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires, uses_cap = _expiry(ttl_hours), max(0, int(max_uses or 0))
    invite_id = _sys(graph).create_entity("content", {
        "type": "crew_invite", "crew_id": crew_id, "crew_name": crew["attrs"].get("name", "?"),
        "token_hash": _hash_token(token), "created_by": by or "",
        "created_at": now_iso(), "expires_at": expires,
        "max_uses": uses_cap, "uses": 0, "revoked": False,
    }, source=source)
    return {"invite_id": invite_id, "crew_id": crew_id,
            "crew_name": crew["attrs"].get("name", "?"), "token": token,
            "expires_at": expires, "max_uses": uses_cap}


def _resolve(session, token: str):
    if not token:
        return None
    hits = session.find_entities(
        "content", {"type": "crew_invite", "token_hash": _hash_token(token)}, limit=1)
    return hits[0] if hits else None


def redeem(graph: Graph, token: str, person_id: str, source: str = MODULE) -> dict:
    """Join a crew by holding its link.

    Deliberately does not read the crew entity: the invite was issued by a verified admin,
    so the link itself is the authority. That is also what makes a link work for a PRIVATE
    crew across accounts — an invited traveller can join a group they could never have
    found, without the crew ever being listed anywhere.

    Every refusal reads the same ("that link isn't valid") so a bad token can't be used to
    probe which crews exist or whether a link was merely expired.
    """
    session = _sys(graph)
    invite = _resolve(session, token)
    if invite is None or not _is_active(invite["attrs"]):
        raise ValueError("that link isn't valid")
    a = invite["attrs"]
    crew_id = a["crew_id"]

    crew_session = graph.session(MODULE, crews.SCOPES)
    if not crews._subject_exists(crew_session, person_id):
        raise ValueError("unknown person")

    state = crews._state_of(crew_session, crew_id, person_id)
    if state == crews.BLOCKED:
        # A link is an invitation, not an amnesty. Blocks outrank invites, always.
        raise ValueError("that link isn't valid")
    if state in (crews.ADMIN, crews.MEMBER):
        # Already in — idempotent, and it must not burn one of the link's uses.
        return {**_crew_result(crew_session, crew_id, a, person_id), "joined": False, "already": True}

    crews._set_state(crew_session, crew_id, person_id, crews.MEMBER, source)
    session.update_entity(invite["id"], {"uses": a.get("uses", 0) + 1}, source=source)
    return {**_crew_result(crew_session, crew_id, a, person_id), "joined": True, "already": False}


def _crew_result(crew_session, crew_id: str, a: dict, subject: str | None = None) -> dict:
    """The crew as the joiner can now see it — falling back to the invite's own record.

    A private crew still isn't readable through the normal paths even by a member, so the
    fallback is what stops a successful join from failing on the way back out.
    """
    try:
        return crews._reload_view(crew_session, crew_id, subject)
    except ValueError:
        return {"id": crew_id, "name": a.get("crew_name", "?")}


def revoke(graph: Graph, invite_id: str, by: str | None = None, source: str = MODULE) -> dict:
    """Kill a link. A shared secret you cannot withdraw is not a capability, it's a leak."""
    session = _sys(graph)
    invite = session.get_entity(invite_id)
    if invite is None or invite["attrs"].get("type") != "crew_invite":
        raise ValueError("unknown invite")
    crew_session = graph.session(MODULE, crews.SCOPES)
    _crew, mine = crews._load_visible(crew_session, invite["attrs"]["crew_id"], by)
    crews._require_admin(crew_session, invite["attrs"]["crew_id"], by, source, mine)

    session.update_entity(invite_id, {"revoked": True}, source=source)
    return {"invite_id": invite_id, "revoked": True}


def for_crew(graph: Graph, crew_id: str, by: str | None = None, limit: int = 50,
             source: str = MODULE) -> list[dict]:
    """Links issued for a crew, admin-only. Shows their state, never their secret."""
    crew_session = graph.session(MODULE, crews.SCOPES)
    _crew, mine = crews._load_visible(crew_session, crew_id, by)
    crews._require_admin(crew_session, crew_id, by, source, mine)
    return [_view(i) for i in _sys(graph).find_entities(
        "content", {"type": "crew_invite", "crew_id": crew_id}, limit=limit)]
