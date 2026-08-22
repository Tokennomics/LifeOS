"""Meetups — turning a sentence in the room into something you can actually join.

The city room works, and it stops one step short. "Sunset at the viewpoint around seven,
anyone?" is the most useful thing anybody types in there, and it is also the thing that
scrolls away in ten minutes, that nobody can say yes to except by typing "me too", and that
gives you no idea who else is coming. Hostelworld solved this years ago and calls them
Linkups; this is the same object.

A meetup is deliberately small: **a thing, a place, a time, and the list of who is coming.**
Not an event with tickets, not a crew with a membership lifecycle — those both already exist
here and neither fits a stranger saying "I'm walking up the hill at seven".

The rules follow the room's, because it is the same public space:

- **System-owned**, so one city's plans exist once rather than per account.
- **They expire on their own**, `GRACE_HOURS` after they start. A list of plans that is
  mostly last week's is worse than no list — and, as with chat, a durable record of where
  somebody was is not a thing to keep.
- **The mute list applies.** Somebody you muted should not appear at the top of your
  evening's options.
- **The organiser is the session, never the body.** "Ana is organising this" is a claim with
  real-world consequences.
- **Place is free text, never coordinates.** City granularity is the promise the whole city
  surface makes; a meetup is exactly where somebody would be tempted to break it.

`SAFETY_NOTE` travels with every meetup rather than living in a settings page. Meeting a
stranger somewhere public is the first line of every solo-travel safety guide written, and
the moment it is useful is the moment somebody is deciding to go — not a screen they visited
once during signup.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat

MODULE = "city.meetups"
SCOPES = {"content:read", "content:write"}
RECORD = "city_meetup"

MAX_TITLE = 120
MAX_PLACE = 120
MAX_NOTE = 300
#: How long a meetup stays listed after its start time — long enough that someone running
#: late can still find it, short enough that the list is tonight's rather than last week's.
GRACE_HOURS = 6
#: Nobody plans a coffee eleven months out; a far-future date is a mistake or a spammer.
MAX_DAYS_AHEAD = 60
MAX_PER_WINDOW = 5
WINDOW_MINUTES = 60
MAX_LISTED = 50

SAFETY_NOTE = ("Meet somewhere public the first time, and tell someone where you are going.")


class MeetupError(ValueError):
    """A meetup that cannot be created or joined."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        when = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    # A naive timestamp from a client is treated as UTC rather than refused: the alternative
    # is rejecting half the world's date pickers over a missing suffix.
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _live(row: dict, now) -> bool:
    if row["attrs"].get("cancelled"):
        return False
    starts = _parse(row["attrs"].get("starts_at"))
    return starts is not None and starts + datetime.timedelta(hours=GRACE_HOURS) > now


def create(graph: Graph, city: str, *, title: str, starts_at: str, place: str = "",
           note: str = "", organiser_id: str, organiser_handle: str = "",
           source: str = MODULE) -> dict:
    """Propose something. The organiser is counted as going — nobody proposes a walk they
    are not on, and an attendee list that starts at zero reads as an idea nobody backs."""
    room = chat.slug(city)
    title = str(title or "").strip()[:MAX_TITLE]
    if not title:
        raise MeetupError("what is the plan?")
    if not organiser_id:
        raise MeetupError("sign in first")

    when = _parse(starts_at)
    if when is None:
        raise MeetupError("when? give a date and time")
    now = _now()
    if when + datetime.timedelta(hours=GRACE_HOURS) < now:
        raise MeetupError("that is already over")
    if when > now + datetime.timedelta(days=MAX_DAYS_AHEAD):
        raise MeetupError(f"keep it within {MAX_DAYS_AHEAD} days")

    session = _sys(graph)
    recent = [row for row in session.find_entities(
        "content", {"type": RECORD, "city": room, "organiser_id": organiser_id}, limit=100)
        if (made := _parse(row["attrs"].get("created_at"))) is not None
        and made > now - datetime.timedelta(minutes=WINDOW_MINUTES)]
    if len(recent) >= MAX_PER_WINDOW:
        raise MeetupError("that is a lot of plans at once — give it an hour")

    meetup_id = session.create_entity("content", {
        "type": RECORD, "city": room, "city_label": str(city or "").strip()[:80],
        "title": title, "place": str(place or "").strip()[:MAX_PLACE],
        "note": str(note or "").strip()[:MAX_NOTE],
        "starts_at": when.isoformat(),
        "organiser_id": organiser_id, "organiser_handle": str(organiser_handle or "")[:80],
        "going": [organiser_id], "handles": {organiser_id: str(organiser_handle or "")[:80]},
        "created_at": now_iso(), "cancelled": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"meetup_id": meetup_id, "city": room, "title": title,
            "starts_at": when.isoformat(), "safety_note": SAFETY_NOTE}


def _load(session, meetup_id: str) -> dict:
    row = session.get_entity(meetup_id)
    if row is None or row["attrs"].get("type") != RECORD:
        raise MeetupError("unknown meetup")
    return row


def join(graph: Graph, meetup_id: str, *, account_id: str, handle: str = "",
         source: str = MODULE) -> dict:
    session = _sys(graph)
    row = _load(session, meetup_id)
    if row["attrs"].get("cancelled"):
        raise MeetupError("that meetup was called off")
    if not _live(row, _now()):
        raise MeetupError("that one has already happened")

    going = list(row["attrs"].get("going") or [])
    handles = dict(row["attrs"].get("handles") or {})
    if account_id not in going:
        going.append(account_id)
    handles[account_id] = str(handle or "")[:80]
    session.update_entity(meetup_id, {"going": going, "handles": handles}, source=source)
    return {"joined": True, "meetup_id": meetup_id, "going": len(going),
            "safety_note": SAFETY_NOTE}


def leave(graph: Graph, meetup_id: str, *, account_id: str, source: str = MODULE) -> dict:
    """Drop out. The organiser leaving cancels it — a plan whose author is not coming is
    not a plan, and leaving the others to discover that at the viewpoint is worse."""
    session = _sys(graph)
    row = _load(session, meetup_id)

    if row["attrs"].get("organiser_id") == account_id:
        session.update_entity(meetup_id, {"cancelled": True}, source=source)
        return {"left": True, "cancelled": True, "meetup_id": meetup_id}

    going = [person for person in (row["attrs"].get("going") or [])
             if person != account_id]
    session.update_entity(meetup_id, {"going": going}, source=source)
    return {"left": True, "cancelled": False, "meetup_id": meetup_id,
            "going": len(going)}


def cancel(graph: Graph, meetup_id: str, *, account_id: str, source: str = MODULE) -> dict:
    session = _sys(graph)
    row = _load(session, meetup_id)
    if row["attrs"].get("organiser_id") != account_id:
        raise MeetupError("only the organiser can call it off")
    session.update_entity(meetup_id, {"cancelled": True}, source=source)
    return {"cancelled": True, "meetup_id": meetup_id}


def _render(row: dict, viewer_id: str, hidden: set) -> dict:
    attrs = row["attrs"]
    handles = attrs.get("handles") or {}
    going = [person for person in (attrs.get("going") or []) if person not in hidden]
    return {
        "meetup_id": row["id"],
        "city": attrs.get("city", ""),
        "title": attrs.get("title", ""),
        "place": attrs.get("place", ""),
        "note": attrs.get("note", ""),
        "starts_at": attrs.get("starts_at", ""),
        "organiser_id": attrs.get("organiser_id", ""),
        "organiser_handle": attrs.get("organiser_handle") or "someone",
        # The point of the whole object: you can see who is coming before you decide.
        "going": [{"account_id": person, "handle": handles.get(person) or "someone"}
                  for person in going],
        "going_count": len(going),
        "you_are_going": viewer_id in (attrs.get("going") or []),
        "yours": attrs.get("organiser_id") == viewer_id,
    }


def listing(graph: Graph, city: str, *, viewer_id: str = "",
            limit: int = MAX_LISTED) -> dict:
    """Tonight's options in this city, soonest first."""
    room = chat.slug(city)
    now = _now()
    hidden = chat.muted_by(graph, viewer_id)

    rows = [row for row in _sys(graph).find_entities(
        "content", {"type": RECORD, "city": room}, limit=MAX_LISTED * 4)
        if _live(row, now) and row["attrs"].get("organiser_id") not in hidden]
    rows.sort(key=lambda r: str(r["attrs"].get("starts_at", "")))

    return {"city": room,
            "meetups": [_render(row, viewer_id, hidden) for row in rows[:limit]],
            "safety_note": SAFETY_NOTE}


def upcoming_for(graph: Graph, account_id: str, limit: int = 20) -> list[dict]:
    """Everything you said you would go to, wherever it is — so a plan made in one city's
    room does not vanish the moment you look at a different room."""
    now = _now()
    mine = []
    for row in _sys(graph).find_entities("content", {"type": RECORD}, limit=500):
        if not _live(row, now):
            continue
        if account_id in (row["attrs"].get("going") or []):
            mine.append(_render(row, account_id, set()))
    mine.sort(key=lambda m: m["starts_at"])
    return mine[:limit]
