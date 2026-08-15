"""Crew beacons — "I am going now, who is coming?"

`/crews/beacon` returned `broadcasted: True` and "⚡ Outing Squad Beacon broadcasted!
'Coffee & Quick Bouldering' in next 30 mins." Nothing was broadcast anywhere. No crew member
could see it, there was no way to answer it, and the activity defaulted to a hardcoded one
when the caller sent nothing — so the app cheerfully told you it had rallied your crew
around an activity you never named.

The word "broadcast" is the whole problem. This app sends nothing: there is no push, no SMS,
no notification of any kind, and a feature that implies otherwise changes how somebody
behaves — they stop asking, because they think they already have.

So a beacon is a **short-lived row your crew can see when they open the app**, and the
claims are exact:

- **`push_delivered` is false**, always, and `can_see_it` counts the crew members who could
  read it — not the ones who were told. Same rule as SafeWalk, for the same reason.
- **It is answerable.** A beacon nobody can say "I'm in" to is a broadcast into the void,
  which is what the prop was. Joining is a row, and the beacon shows who is in.
- **It expires in minutes, not days.** "Coffee in the next 30" is worthless at midnight, and
  a stale beacon list is a list people stop reading.
- **Crew members only**, to raise one, to see one, and to join one.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.crews import crews

MODULE = "crews.beacons"
SCOPES = {"content:read", "content:write"}
RECORD = "crew_beacon"
JOIN = "crew_beacon_join"

MAX_ACTIVITY = 120
MAX_NOTE = 200
DEFAULT_MINUTES = 60
MAX_MINUTES = 12 * 60
MAX_LISTED = 50

NOT_SENT = ("Nobody was messaged. Your crew sees this when they next open the app — this "
            "app cannot notify anyone.")


class BeaconError(ValueError):
    """A beacon that cannot be raised, seen or joined."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _text(value, cap: int) -> str:
    return str(value or "").strip()[:cap]


def _require_member(graph: Graph, crew_id: str, account_id: str) -> None:
    if not account_id:
        raise BeaconError("sign in first")
    if not crews.is_member(graph, crew_id, account_id):
        raise BeaconError("no such beacon")


def _live(attrs: dict, now=None) -> bool:
    if attrs.get("stood_down"):
        return False
    until = _parse(attrs.get("until", ""))
    return bool(until and until > (now or _now()))


def raise_beacon(graph: Graph, *, crew_id: str, activity: str, account_id: str,
                 handle: str = "", minutes: int = DEFAULT_MINUTES, note: str = "",
                 place: str = "", source: str = MODULE) -> dict:
    """Say you are going, and for how long the offer stands."""
    crew_id = str(crew_id or "").strip()
    _require_member(graph, crew_id, account_id)
    activity = _text(activity, MAX_ACTIVITY)
    if not activity:
        # The prop defaulted this to "Coffee & Quick Bouldering", so an empty form told the
        # crew you were doing something you had not said.
        raise BeaconError("up for what?")

    if minutes is None:
        minutes = DEFAULT_MINUTES
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise BeaconError("minutes must be a number")
    if minutes < 5 or minutes > MAX_MINUTES:
        raise BeaconError(f"pick between 5 and {MAX_MINUTES} minutes")

    session = _sys(graph)
    # One live beacon each per crew: two overlapping "I'm going now" rows from one person is
    # how a beacon list stops being worth opening.
    for row in session.find_entities(
            "content", {"type": RECORD, "crew_id": crew_id, "account_id": account_id},
            limit=20):
        if _live(row["attrs"]):
            session.update_entity(row["id"], {"stood_down": True}, source=source)

    beacon_id = session.create_entity("content", {
        "type": RECORD, "crew_id": crew_id, "account_id": account_id,
        "handle": _text(handle, 80), "activity": activity,
        "place": _text(place, MAX_ACTIVITY), "note": _text(note, MAX_NOTE),
        "created_at": now_iso(),
        "until": (_now() + datetime.timedelta(minutes=minutes)).isoformat(),
        "stood_down": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    reach = len(crews.members(graph, crew_id))
    return {"raised": True, "beacon_id": beacon_id, "crew_id": crew_id,
            "activity": activity, "minutes": minutes,
            # The honest replacement for `broadcasted: True`.
            "push_delivered": False,
            "can_see_it": max(0, reach - 1),
            "delivery_note": NOT_SENT}


def _beacon(graph: Graph, beacon_id: str, account_id: str) -> dict:
    row = _sys(graph).get_entity(str(beacon_id or "").strip())
    if row is None or row["attrs"].get("type") != RECORD:
        raise BeaconError("no such beacon")
    _require_member(graph, row["attrs"].get("crew_id", ""), account_id)
    return row


def _joins(graph: Graph, beacon_id: str) -> list[dict]:
    return [r for r in _sys(graph).find_entities(
        "content", {"type": JOIN, "beacon_id": beacon_id}, limit=MAX_LISTED * 4)
        if not r["attrs"].get("withdrawn")]


def join(graph: Graph, *, beacon_id: str, account_id: str, handle: str = "",
         source: str = MODULE) -> dict:
    """Say you are in. The part the prop had no room for."""
    row = _beacon(graph, beacon_id, account_id)
    if not _live(row["attrs"]):
        raise BeaconError("that one has expired")
    if row["attrs"].get("account_id") == account_id:
        raise BeaconError("it is yours — you are already in it")

    session = _sys(graph)
    for previous in _joins(graph, row["id"]):
        if previous["attrs"].get("account_id") == account_id:
            return {"joined": True, "beacon_id": row["id"], "already": True,
                    **_render(graph, row, account_id)}

    session.create_entity("content", {
        "type": JOIN, "beacon_id": row["id"], "crew_id": row["attrs"].get("crew_id", ""),
        "account_id": account_id, "handle": _text(handle, 80),
        "created_at": now_iso(), "withdrawn": False,
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"joined": True, "beacon_id": row["id"], **_render(graph, row, account_id)}


def leave(graph: Graph, *, beacon_id: str, account_id: str,
          source: str = MODULE) -> dict:
    """Change your mind. Better than a crew waiting for somebody who is not coming."""
    row = _beacon(graph, beacon_id, account_id)
    session = _sys(graph)
    dropped = 0
    for existing in _joins(graph, row["id"]):
        if existing["attrs"].get("account_id") == account_id:
            session.update_entity(existing["id"], {"withdrawn": True}, source=source)
            dropped += 1
    return {"left": True, "beacon_id": row["id"], "was_in": bool(dropped),
            **_render(graph, row, account_id)}


def stand_down(graph: Graph, *, beacon_id: str, account_id: str,
               source: str = MODULE) -> dict:
    """Cancel your own beacon."""
    row = _beacon(graph, beacon_id, account_id)
    if row["attrs"].get("account_id") != account_id:
        raise BeaconError("that is not yours to cancel")
    if not _live(row["attrs"]):
        return {"stood_down": True, "beacon_id": row["id"], "already": True}
    _sys(graph).update_entity(row["id"], {"stood_down": True}, source=source)
    return {"stood_down": True, "beacon_id": row["id"]}


def _render(graph: Graph, row: dict, viewer_id: str, now=None) -> dict:
    attrs = row["attrs"]
    joins = _joins(graph, row["id"])
    until = _parse(attrs.get("until", ""))
    left = int((until - (now or _now())).total_seconds() // 60) if until else 0
    return {"beacon_id": row["id"], "activity": attrs.get("activity", ""),
            "place": attrs.get("place", ""), "note": attrs.get("note", ""),
            "handle": attrs.get("handle") or "someone",
            "mine": attrs.get("account_id") == viewer_id,
            "minutes_left": max(0, left),
            "coming": [j["attrs"].get("handle") or "someone" for j in joins],
            "coming_count": len(joins),
            "you_are_in": any(j["attrs"].get("account_id") == viewer_id for j in joins),
            "created_at": attrs.get("created_at", "")}


def live(graph: Graph, *, crew_id: str, account_id: str,
         limit: int = MAX_LISTED) -> dict:
    """What your crew is up for right now. Expired beacons are simply not here."""
    crew_id = str(crew_id or "").strip()
    _require_member(graph, crew_id, account_id)
    now = _now()
    items = [_render(graph, row, account_id, now)
             for row in _sys(graph).find_entities(
                 "content", {"type": RECORD, "crew_id": crew_id}, limit=MAX_LISTED * 4)
             if _live(row["attrs"], now)]
    items.sort(key=lambda b: b["created_at"], reverse=True)
    return {"crew_id": crew_id, "beacons": items[:limit], "empty": not items,
            "push_delivered": False,
            "suggestion": "" if items else (
                "Nothing live. Raising one takes a sentence and expires on its own."),
            "delivery_note": NOT_SENT}
