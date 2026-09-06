"""Who has volunteered to help new arrivals in a city.

`GET /community/ambassadors` returned a launch heatmap: Lisbon LIVE with 1,420 active
members, Tokyo 980, Barcelona "LAUNCHING_SOON, 85%, 15 more members to unlock". Every number
was a constant, the four cities were the same on every deployment, and the progress bars
measured nothing — an instance installed a minute earlier reported 2,400 members it did not
have. It was also the only place in the app that told somebody a feature was locked until
enough people joined; nothing was ever unlocked, because there was nothing behind it.

The honest object is much smaller and it is not a heatmap. An ambassador here is **a row an
account created about itself**: "I am in this city and happy to be asked things by people
who have just arrived". That is a claim by the person, so:

- **Only you can opt yourself in.** Nobody can nominate anybody, and nobody is listed because
  a count crossed a threshold.
- **Nothing is vetted.** `verified` is not a key here. Volunteering is one person's word,
  the same way a vouch is (`modules/social/trust.py`), and the response says so.
- **It expires**, like an arrival announcement, because "I'll help newcomers" is a statement
  about this season and not for ever — and a stale list of people who have moved away is
  the failure mode that kills the feature.
- **Opting out is immediate**, and the row goes with it rather than being flagged.
- **Empty is empty.** On a new instance nobody has volunteered, and the true answer is a
  list of length zero with a sentence naming what would fill it.

There is no member count per city here either. `platform.overview.globe()` already counts
what is actually in the graph, and a second count computed differently is how two screens
come to disagree.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat

MODULE = "community.ambassadors"
SCOPES = {"content:read", "content:write"}
RECORD = "city_ambassador"

MAX_NOTE = 200
MAX_LISTED = 100
#: How long a volunteer stays listed without renewing. A season, not for ever.
DEFAULT_DAYS = 90
MAX_DAYS = 180

NOT_VETTED = ("Nobody has checked this. An ambassador is somebody who said they are happy "
              "to be asked things, which is their word and nothing more.")


class AmbassadorError(ValueError):
    """A volunteer row that cannot be written."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        when = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _live(attrs: dict, now) -> bool:
    if attrs.get("withdrawn"):
        return False
    until = _parse(attrs.get("expires_at"))
    return until is None or until > now


def _mine(session, room: str, account_id: str):
    rows = session.find_entities("content", {"type": RECORD, "city": room,
                                             "account_id": account_id}, limit=20)
    return rows[0] if rows else None


def opt_in(graph: Graph, city: str, *, account_id: str, handle: str = "", note: str = "",
           days: int = DEFAULT_DAYS, source: str = MODULE) -> dict:
    """Volunteer yourself, in one city. Renewing replaces your own row rather than adding
    a second one — two entries for one person reads as two people."""
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise AmbassadorError("which city?")
    if not account_id:
        raise AmbassadorError("sign in first")
    try:
        days = int(days or DEFAULT_DAYS)
    except (TypeError, ValueError):
        raise AmbassadorError("days must be a number")
    if not 1 <= days <= MAX_DAYS:
        raise AmbassadorError(f"between 1 and {MAX_DAYS} days")

    now = _now()
    expires = (now + datetime.timedelta(days=days)).isoformat()
    attrs = {"type": RECORD, "city": room, "city_label": str(city or "").strip()[:80],
             "account_id": account_id, "handle": str(handle or "")[:80],
             "note": str(note or "").strip()[:MAX_NOTE],
             "expires_at": expires, "withdrawn": False, "created_at": now_iso()}

    session = _sys(graph)
    existing = _mine(session, room, account_id)
    if existing is not None:
        session.update_entity(existing["id"], {k: v for k, v in attrs.items()
                                               if k not in ("type", "created_at")},
                              source=source)
        row_id = existing["id"]
    else:
        row_id = session.create_entity("content", attrs, source=source,
                                       owner_id=SYSTEM_OWNER)

    return {"ambassador": True, "ambassador_id": row_id, "city": room,
            "account_id": account_id, "handle": str(handle or "")[:80],
            "expires_at": expires, "vetted": False, "not_vetted": NOT_VETTED}


def opt_out(graph: Graph, city: str, *, account_id: str, source: str = MODULE) -> dict:
    """Stand down. Immediate, and it is your own row you are taking back."""
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise AmbassadorError("which city?")
    session = _sys(graph)
    existing = _mine(session, room, account_id)
    if existing is None:
        return {"ambassador": False, "city": room, "was_listed": False}
    session.update_entity(existing["id"], {"withdrawn": True}, source=source)
    return {"ambassador": False, "city": room, "was_listed": True}


def listing(graph: Graph, city: str, *, viewer_id: str = "",
            limit: int = MAX_LISTED) -> dict:
    """Who has volunteered in this city, and nobody else."""
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise AmbassadorError("which city?")
    now = _now()
    hidden = chat.muted_by(graph, viewer_id) if viewer_id else set()

    rows = [row for row in _sys(graph).find_entities(
        "content", {"type": RECORD, "city": room}, limit=MAX_LISTED * 4)
        if _live(row["attrs"], now) and row["attrs"].get("account_id") not in hidden]
    rows.sort(key=lambda r: str(r["attrs"].get("created_at", "")))

    people = [{"account_id": row["attrs"].get("account_id", ""),
               "handle": row["attrs"].get("handle") or "someone",
               "note": row["attrs"].get("note", ""),
               "since": row["attrs"].get("created_at", ""),
               "you": row["attrs"].get("account_id") == viewer_id}
              for row in rows[:limit]]

    return {"city": room, "ambassadors": people, "count": len(people),
            "empty": not people, "vetted": False, "not_vetted": NOT_VETTED,
            "you_are_one": any(person["you"] for person in people),
            "suggestion": "" if people else (
                "Nobody has volunteered in this city yet. Anyone signed in can, with "
                "`POST /v1/community/ambassadors`.")}
