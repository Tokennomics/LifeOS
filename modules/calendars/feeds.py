"""Calendar feed tokens — the only way an .ics subscription can actually work.

A crew's `.ics` lives behind the session bearer token, which is correct for the app and
useless for the thing the feature is for: a calendar client subscribes by URL, on a schedule,
with no browser and no way to send an `Authorization` header. So "Subscribe: <link>" was a
false claim in exactly the way this whole effort exists to remove — the link 401s the moment
anything other than the signed-in app fetches it.

A feed token makes the URL self-authenticating, which means the URL *is* the credential, and
it is held to the rules that follow from that:

- **Read-only, and scoped to one crew.** It grants exactly one thing: the calendar of the
  crew it was minted for. Not the account, not another crew.
- **Only the SHA-256 is stored**, and the token is shown once, like every other capability
  in this repo.
- **Revocable**, immediately, because a URL pasted into a calendar client will end up in
  places nobody planned — a shared laptop, an exported config, a screenshot.
- **It expires.** A subscription URL that works forever is one nobody ever revokes.
- **It is never a login.** Resolving one yields a crew id and nothing else; there is no
  account attached to it and no way to widen it into one.
"""

import datetime
import hashlib
import secrets

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.crews import crews

MODULE = "calendars.feeds"
SCOPES = {"content:read", "content:write"}
RECORD = "calendar_feed_token"

TOKEN_BYTES = 32
DEFAULT_DAYS = 365
MAX_DAYS = 365 * 2
MAX_PER_CREW = 10


class FeedError(ValueError):
    """A feed token that cannot be minted or resolved."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def mint(graph: Graph, *, crew_id: str, account_id: str, days: int = DEFAULT_DAYS,
         source: str = MODULE) -> dict:
    """A subscribe URL for a crew you are in. Returned once and never again."""
    crew_id = str(crew_id or "").strip()
    if not account_id:
        raise FeedError("sign in first")
    if not crews.is_member(graph, crew_id, account_id):
        raise FeedError("no such crew")
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise FeedError("days must be a number")
    days = max(1, min(days, MAX_DAYS))

    session = _sys(graph)
    live = [r for r in session.find_entities(
        "content", {"type": RECORD, "crew_id": crew_id, "account_id": account_id},
        limit=50) if not r["attrs"].get("revoked")]
    if len(live) >= MAX_PER_CREW:
        raise FeedError("that is a lot of subscribe links — revoke one first")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    feed_id = session.create_entity("content", {
        "type": RECORD, "crew_id": crew_id, "account_id": account_id,
        "token_hash": _hash(token), "created_at": now_iso(),
        "expires_at": (_now() + datetime.timedelta(days=days)).isoformat(),
        "revoked": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"feed_id": feed_id, "crew_id": crew_id, "token": token,
            "path": f"/v1/crews/{crew_id}/export.ics?token={token}",
            "expires_in_days": days,
            "read_only": True,
            "warning": ("Anyone with this link can read this crew's calendar. It is a URL, "
                        "so treat it like one — revoke it if it goes somewhere it should "
                        "not.")}


def crew_for(graph: Graph, token: str) -> str:
    """The crew a token opens, or "" — never an account, and never a reason why not."""
    token = str(token or "").strip()
    if not token:
        return ""
    hits = _sys(graph).find_entities("content", {"type": RECORD, "token_hash": _hash(token)},
                                     limit=2)
    for row in hits:
        attrs = row["attrs"]
        if attrs.get("revoked"):
            continue
        expires = attrs.get("expires_at", "")
        if expires and expires < now_iso():
            continue
        return attrs.get("crew_id", "")
    return ""


def revoke(graph: Graph, *, feed_id: str, account_id: str,
           source: str = MODULE) -> dict:
    """Stop a link working. Whoever minted it, or an admin of the crew."""
    if not account_id:
        raise FeedError("sign in first")
    session = _sys(graph)
    row = session.get_entity(str(feed_id or "").strip())
    if row is None or row["attrs"].get("type") != RECORD:
        raise FeedError("no such link")
    attrs = row["attrs"]
    if attrs.get("account_id") != account_id and \
            not crews.is_admin(graph, attrs.get("crew_id", ""), account_id):
        raise FeedError("that is not yours to revoke")
    session.update_entity(row["id"], {"revoked": True, "revoked_at": now_iso()},
                          source=source)
    return {"revoked": True, "feed_id": row["id"]}


def listing(graph: Graph, *, crew_id: str, account_id: str) -> dict:
    """Your live subscribe links for a crew. Never the tokens — those are unreadable."""
    crew_id = str(crew_id or "").strip()
    if not account_id:
        raise FeedError("sign in first")
    if not crews.is_member(graph, crew_id, account_id):
        raise FeedError("no such crew")
    items = [{"feed_id": r["id"], "created_at": r["attrs"].get("created_at", ""),
              "expires_at": r["attrs"].get("expires_at", "")}
             for r in _sys(graph).find_entities(
                 "content", {"type": RECORD, "crew_id": crew_id,
                             "account_id": account_id}, limit=50)
             if not r["attrs"].get("revoked")]
    items.sort(key=lambda f: f["created_at"], reverse=True)
    return {"crew_id": crew_id, "links": items, "empty": not items}
