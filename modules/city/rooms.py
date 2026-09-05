"""Rooms — a list of people who want to talk, which is not the same as a call.

Three endpoints sold live audio this deployment has no way to carry.
`GET /audio/lounge-spaces` listed two lounges with 8 and 14 listeners and speakers called
Alex, Elena R. and Marcus T., both `LIVE_NOW`, on an instance with no accounts.
`POST /spaces/audio` answered `created: True` and handed back a `room_url` on a host this
deployment does not serve — following it reached nothing, and nothing was stored, so the
list never grew. `POST /voice/crew-huddle` reported "Opus 48kHz Spatial 3D Audio", 18ms
latency, "AI Crowd & Wind Cancellation" and two named people at two bearings.

There is no audio transport here: no media server, no call signalling, no relay
(`platform.capabilities.AUDIO`). Rather than shrink that into a smaller lie — a quieter
codec, fewer listeners — this models the part that does not need one.

**A room is a rendezvous: a title, who opened it, and who has said they are in.** It is the
same shape as a meetup, minus the place and the time, and it is useful for the same reason:
five people who all want to talk about the same thing can find each other, then use whatever
they already use to actually talk. The response says that in `no_audio` rather than implying
it, because a "room" that produces no sound is exactly the kind of thing somebody sits
waiting in.

- **`audio: False` on every response.** Not a status that might become True later on this
  deployment — there is nothing to switch on.
- **Members are accounts**, never a speaker list. Nobody is "speaking", because nothing is
  carrying speech.
- **Rooms expire** (`DEFAULT_HOURS`), like an open synergy signal. A rendezvous list from
  last Tuesday is worse than an empty one.
- **A crew room is private to the crew.** Non-members cannot see it or join it, which is
  the same rule crews already keep everywhere else.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat
from modules.crews import crews
from modules.platform import capabilities

MODULE = "city.rooms"
SCOPES = {"content:read", "content:write", "people:read"}
RECORD = "rendezvous_room"

MAX_TITLE = 120
MAX_NOTE = 300
DEFAULT_HOURS = 6
MAX_HOURS = 24
MAX_LISTED = 50
MAX_PER_WINDOW = 5
WINDOW_MINUTES = 60


def _sentence(text: str) -> str:
    """The capability table's `why` starts mid-sentence by design — it completes "cannot do
    X because…" on the status page. Here it opens one."""
    return text[:1].upper() + text[1:]


#: Why there is no sound, in the words the status page uses.
NO_AUDIO = (_sentence(capabilities.UNAVAILABLE[capabilities.AUDIO]["why"])
            + ". This is a list of people who said they want to talk, not a call — swap a "
              "link to whatever you already use.")


class RoomError(ValueError):
    """A room that cannot be opened, joined or read."""


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
    if attrs.get("closed"):
        return False
    until = _parse(attrs.get("expires_at"))
    return until is not None and until > now


def _hours(value) -> int:
    try:
        hours = int(value or DEFAULT_HOURS)
    except (TypeError, ValueError):
        raise RoomError("hours must be a number")
    if not 1 <= hours <= MAX_HOURS:
        raise RoomError(f"between 1 and {MAX_HOURS} hours")
    return hours


def _crew_member(graph: Graph, crew_id: str, account_id: str) -> bool:
    """Membership decides who sees a crew's room. Asked of `crews`, never stored here —
    a second copy of who is in a crew is a second answer to that question."""
    try:
        return crews.is_member(graph, crew_id, account_id)
    except Exception:
        return False


def open_room(graph: Graph, *, title: str, account_id: str, handle: str = "",
              city: str = "", crew_id: str = "", note: str = "",
              hours: int = DEFAULT_HOURS, source: str = MODULE) -> dict:
    """Open one. Either a city room or a crew room — one of the two has to say where it
    lives, or nobody can ever find it."""
    if not account_id:
        raise RoomError("sign in first")
    title = str(title or "").strip()[:MAX_TITLE]
    if not title:
        raise RoomError("what is it about?")
    crew_id = str(crew_id or "").strip()
    room_city = chat.slug(city) if str(city or "").strip() else ""
    if not (room_city or crew_id):
        raise RoomError("which city, or which crew?")
    if crew_id and not _crew_member(graph, crew_id, account_id):
        raise RoomError("that is not your crew")

    hours = _hours(hours)
    now = _now()
    session = _sys(graph)
    recent = [row for row in session.find_entities(
        "content", {"type": RECORD, "opened_by": account_id}, limit=100)
        if (made := _parse(row["attrs"].get("created_at"))) is not None
        and made > now - datetime.timedelta(minutes=WINDOW_MINUTES)]
    if len(recent) >= MAX_PER_WINDOW:
        raise RoomError("that is a lot of rooms at once — give it an hour")

    room_id = session.create_entity("content", {
        "type": RECORD, "city": room_city,
        "city_label": str(city or "").strip()[:80], "crew_id": crew_id,
        "title": title, "note": str(note or "").strip()[:MAX_NOTE],
        "opened_by": account_id, "opened_by_handle": str(handle or "")[:80],
        "members": [account_id], "handles": {account_id: str(handle or "")[:80]},
        "expires_at": (now + datetime.timedelta(hours=hours)).isoformat(),
        "created_at": now_iso(), "closed": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"opened": True, "room_id": room_id, "title": title, "city": room_city,
            "crew_id": crew_id, "members": 1, "audio": False, "no_audio": NO_AUDIO}


def _load(session, room_id: str) -> dict:
    row = session.get_entity(str(room_id or "").strip())
    if row is None or row["attrs"].get("type") != RECORD:
        raise RoomError("unknown room")
    return row


def _visible(graph: Graph, attrs: dict, account_id: str) -> bool:
    crew_id = attrs.get("crew_id") or ""
    return not crew_id or _crew_member(graph, crew_id, account_id)


def join(graph: Graph, room_id: str, *, account_id: str, handle: str = "",
         source: str = MODULE) -> dict:
    """Say you are in. Joining a room is joining a list, and that is all it is."""
    if not account_id:
        raise RoomError("sign in first")
    session = _sys(graph)
    row = _load(session, room_id)
    if not _live(row["attrs"], _now()):
        raise RoomError("that room is closed")
    if not _visible(graph, row["attrs"], account_id):
        raise RoomError("that is not your crew")

    members = list(row["attrs"].get("members") or [])
    handles = dict(row["attrs"].get("handles") or {})
    if account_id not in members:
        members.append(account_id)
    handles[account_id] = str(handle or "")[:80]
    session.update_entity(row["id"], {"members": members, "handles": handles},
                          source=source)
    return {"joined": True, "room_id": row["id"], "members": len(members),
            "audio": False, "no_audio": NO_AUDIO}


def leave(graph: Graph, room_id: str, *, account_id: str, source: str = MODULE) -> dict:
    """Drop out. Whoever opened it leaving closes it, the same rule a meetup keeps."""
    session = _sys(graph)
    row = _load(session, room_id)
    if row["attrs"].get("opened_by") == account_id:
        session.update_entity(row["id"], {"closed": True}, source=source)
        return {"left": True, "closed": True, "room_id": row["id"], "audio": False}
    members = [person for person in (row["attrs"].get("members") or [])
               if person != account_id]
    session.update_entity(row["id"], {"members": members}, source=source)
    return {"left": True, "closed": False, "room_id": row["id"],
            "members": len(members), "audio": False}


def _render(row: dict, viewer_id: str, hidden: set) -> dict:
    attrs = row["attrs"]
    handles = attrs.get("handles") or {}
    members = [person for person in (attrs.get("members") or []) if person not in hidden]
    return {
        "room_id": row["id"], "title": attrs.get("title", ""),
        "note": attrs.get("note", ""), "city": attrs.get("city", ""),
        "crew_id": attrs.get("crew_id", ""),
        "opened_by": attrs.get("opened_by", ""),
        "opened_by_handle": attrs.get("opened_by_handle") or "someone",
        "members": [{"account_id": person, "handle": handles.get(person) or "someone"}
                    for person in members],
        "member_count": len(members),
        "you_are_in": viewer_id in (attrs.get("members") or []),
        "expires_at": attrs.get("expires_at", ""),
        # Named on every room, not only in the envelope, because a client that renders one
        # room on its own must still say there is no sound.
        "audio": False,
    }


def listing(graph: Graph, *, city: str = "", crew_id: str = "", viewer_id: str = "",
            limit: int = MAX_LISTED) -> dict:
    """Rooms open right now in a city, or in one of your crews. Empty is empty."""
    crew_id = str(crew_id or "").strip()
    room_city = chat.slug(city) if str(city or "").strip() else ""
    if not (room_city or crew_id):
        raise RoomError("which city, or which crew?")
    if crew_id and viewer_id and not _crew_member(graph, crew_id, viewer_id):
        raise RoomError("that is not your crew")

    query = {"type": RECORD}
    query["crew_id"] = crew_id if crew_id else ""
    if room_city:
        query["city"] = room_city

    now = _now()
    hidden = chat.muted_by(graph, viewer_id) if viewer_id else set()
    rows = [row for row in _sys(graph).find_entities("content", query,
                                                     limit=MAX_LISTED * 4)
            if _live(row["attrs"], now)
            and row["attrs"].get("opened_by") not in hidden]
    rows.sort(key=lambda r: str(r["attrs"].get("created_at", "")), reverse=True)
    rooms = [_render(row, viewer_id, hidden) for row in rows[:limit]]

    return {"city": room_city, "crew_id": crew_id, "rooms": rooms, "count": len(rooms),
            "empty": not rooms, "audio": False, "no_audio": NO_AUDIO,
            "suggestion": "" if rooms else (
                "No rooms are open here. Anyone signed in can open one with "
                "`POST /v1/spaces/audio`, and it is a rendezvous list rather than a call.")}
