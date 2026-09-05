"""What a venue has actually said it is putting on.

`GET /venues/programs` returned two programmes on every deployment: a bouldering league at
Vertical Wall Climbing Gym "Tuesdays 19:00 & Fridays 20:00" with "15% off for ConnectOS Crew
Members", and a cupping morning at Fabrica Coffee Roasters. `POST /venues/program` answered
`published: True` and stored nothing — publish twice, read back, and the list was still the
same two. Neither venue had agreed to anything, and somebody who turned up at 08:30 on a
Wednesday expecting a free espresso tasting would have found an ordinary coffee shop.

So this is the smallest object that makes the read true: **a venue, a title, a start, and
who posted it.**

- **A programme is somebody's post about a place, not the place's own word.** Anybody signed
  in can add one — that is how a regular tells the room about the Tuesday night league — so
  every entry carries `posted_by`, and the reader can see it came from a person rather than
  from the venue. Nothing here is `verified` and nothing is `official`; the old copy said
  "Official Venue Program published" about a dict literal.
- **System-owned and city-scoped**, like meetups and the room: a city's programme exists
  once rather than once per account.
- **Upcoming only.** A list that is mostly last month's is worse than an empty one, so an
  entry drops out `GRACE_HOURS` after it starts (or after it ends, when an end is given).
- **No perks, no discounts, no codes.** A discount is a promise on somebody else's till.
  This app cannot make one and cannot check one, and the old copy handed out both.
- **Free text for the venue name.** The map's places are a separate store with their own
  ids; a venue that is not on the map is still a venue, and refusing an entry because
  OpenStreetMap has not heard of it would empty the feature in exactly the cities it is for.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat

MODULE = "venues.programs"
SCOPES = {"content:read", "content:write"}
RECORD = "venue_program"

MAX_VENUE = 120
MAX_TITLE = 120
MAX_NOTE = 300
#: Same grace as a meetup: somebody running late can still find tonight's entry.
GRACE_HOURS = 6
#: A programme announced eleven months out is a mistake or a spammer.
MAX_DAYS_AHEAD = 365
MAX_PER_WINDOW = 10
WINDOW_MINUTES = 60
MAX_LISTED = 50

NOT_OFFICIAL = ("Posted by a person, not by the venue. Nobody here has checked it with the "
                "place, so treat it the way you would treat a note on a noticeboard.")


class ProgramError(ValueError):
    """A programme that cannot be published, or a city that was not named."""


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
    ends = _parse(attrs.get("ends_at")) if attrs.get("ends_at") else None
    starts = _parse(attrs.get("starts_at"))
    if starts is None:
        return False
    return (ends or starts) + datetime.timedelta(hours=GRACE_HOURS) > now


def publish(graph: Graph, city: str, *, venue: str, title: str, starts_at: str,
            ends_at: str = "", note: str = "", account_id: str, handle: str = "",
            source: str = MODULE) -> dict:
    """Add one entry to a city's programme board.

    Every field the old handler defaulted is required here. A default venue name is how an
    empty POST published a programme for a climbing gym in Lisbon that nobody had spoken to.
    """
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise ProgramError("which city?")
    if not account_id:
        raise ProgramError("sign in first")
    venue = str(venue or "").strip()[:MAX_VENUE]
    if not venue:
        raise ProgramError("which venue?")
    title = str(title or "").strip()[:MAX_TITLE]
    if not title:
        raise ProgramError("what is on?")

    when = _parse(starts_at)
    if when is None:
        raise ProgramError("when does it start? give a date and time")
    now = _now()
    if when + datetime.timedelta(hours=GRACE_HOURS) < now:
        raise ProgramError("that is already over")
    if when > now + datetime.timedelta(days=MAX_DAYS_AHEAD):
        raise ProgramError(f"keep it within {MAX_DAYS_AHEAD} days")

    until = _parse(ends_at) if str(ends_at or "").strip() else None
    if str(ends_at or "").strip() and until is None:
        raise ProgramError("that end time is not a date and time")
    if until is not None and until < when:
        raise ProgramError("it cannot end before it starts")

    session = _sys(graph)
    recent = [row for row in session.find_entities(
        "content", {"type": RECORD, "city": room, "posted_by": account_id}, limit=100)
        if (made := _parse(row["attrs"].get("created_at"))) is not None
        and made > now - datetime.timedelta(minutes=WINDOW_MINUTES)]
    if len(recent) >= MAX_PER_WINDOW:
        raise ProgramError("that is a lot of entries at once — give it an hour")

    program_id = session.create_entity("content", {
        "type": RECORD, "city": room, "city_label": str(city or "").strip()[:80],
        "venue": venue, "title": title,
        "starts_at": when.isoformat(),
        "ends_at": until.isoformat() if until else "",
        "note": str(note or "").strip()[:MAX_NOTE],
        "posted_by": account_id, "posted_by_handle": str(handle or "")[:80],
        "created_at": now_iso(), "withdrawn": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"published": True, "program_id": program_id, "city": room, "venue": venue,
            "title": title, "starts_at": when.isoformat(),
            "ends_at": until.isoformat() if until else "",
            "posted_by": account_id, "posted_by_handle": str(handle or "")[:80],
            "official": False, "not_official": NOT_OFFICIAL}


def _render(row: dict, viewer_id: str) -> dict:
    attrs = row["attrs"]
    return {"program_id": row["id"], "city": attrs.get("city", ""),
            "venue": attrs.get("venue", ""), "title": attrs.get("title", ""),
            "starts_at": attrs.get("starts_at", ""), "ends_at": attrs.get("ends_at", ""),
            "note": attrs.get("note", ""),
            "posted_by": attrs.get("posted_by", ""),
            "posted_by_handle": attrs.get("posted_by_handle") or "someone",
            "yours": bool(viewer_id) and attrs.get("posted_by") == viewer_id}


def listing(graph: Graph, city: str, *, venue: str = "", viewer_id: str = "",
            limit: int = MAX_LISTED) -> dict:
    """A city's upcoming programme, soonest first. Empty is empty."""
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise ProgramError("which city?")
    wanted = str(venue or "").strip().lower()
    now = _now()

    rows = [row for row in _sys(graph).find_entities(
        "content", {"type": RECORD, "city": room}, limit=MAX_LISTED * 4)
        if _live(row["attrs"], now)
        and (not wanted or str(row["attrs"].get("venue", "")).lower() == wanted)]
    rows.sort(key=lambda r: str(r["attrs"].get("starts_at", "")))
    programs = [_render(row, viewer_id) for row in rows[:limit]]

    return {"city": room, "venue": str(venue or "").strip(),
            "programs": programs, "count": len(programs), "empty": not programs,
            "not_official": NOT_OFFICIAL,
            "suggestion": "" if programs else (
                "Nothing is on the board for this city yet. Anyone signed in can add what "
                "a venue has told them, with `POST /v1/venues/program`.")}


def withdraw(graph: Graph, program_id: str, *, account_id: str,
             source: str = MODULE) -> dict:
    """Take back an entry. Only whoever posted it can — it is their claim about a place."""
    session = _sys(graph)
    row = session.get_entity(program_id)
    if row is None or row["attrs"].get("type") != RECORD:
        raise ProgramError("unknown programme")
    if row["attrs"].get("posted_by") != account_id:
        raise ProgramError("only whoever posted it can take it down")
    session.update_entity(program_id, {"withdrawn": True}, source=source)
    return {"withdrawn": True, "program_id": program_id}
