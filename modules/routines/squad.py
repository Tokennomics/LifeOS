"""The thing a crew does every week, as real dates a calendar can subscribe to.

`/routines/squad-sync` returned `synced: True`, `recurrence: "Weekly on Wednesdays @ 7:00
AM"` — the same recurrence whatever you asked for — `synced_calendars: 5`, and an
`ics_link` on connectos.app. Nothing was stored, no calendar was touched, and the number 5
was a constant that did not depend on the crew having five members, or any.

The idea underneath is good and is the strongest thing a small group has: the same thing, at
the same time, every week, so nobody has to organise it again. What was missing was the part
that makes it true — the occurrences have to exist as dates, and the calendar link has to be
one this deployment actually serves.

- **A routine is a rule**, and `upcoming` expands it into real dates you can read.
- **The .ics is served from here**, by the exporter this repo already has, so subscribing in
  a calendar app works instead of 404ing on somebody else's domain.
- **Nothing claims to have touched anybody's calendar.** `synced_calendars: 5` was the same
  lie as "your crew has been notified": a subscription is something each person does, so
  what is reported is how many people *could* subscribe.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.crews import crews

MODULE = "routines.squad"
SCOPES = {"content:read", "content:write"}
RECORD = "squad_routine"

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_TITLE = 120
MAX_WEEKS = 26
DEFAULT_WEEKS = 8
MAX_PER_CREW = 20

NOT_SYNCED = ("Nobody's calendar has been touched. Subscribing is something each person "
              "does once, with the link below.")


class RoutineError(ValueError):
    """A routine that cannot be set or read."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _text(value, cap: int = MAX_TITLE) -> str:
    return str(value or "").strip()[:cap]


def _require_member(graph: Graph, crew_id: str, account_id: str) -> None:
    if not account_id:
        raise RoutineError("sign in first")
    if not crews.is_member(graph, crew_id, account_id):
        raise RoutineError("no such routine")


def _weekday(value) -> int:
    day = str(value or "").strip().lower()[:3]
    if day not in DAYS:
        raise RoutineError(f"{value or 'that'} is not a day — use wed, or thu")
    return DAYS.index(day)


def _clock(value) -> tuple:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise RoutineError(f"{text or 'that'} is not a time — use 07:00")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise RoutineError(f"{text} is not a time — use 07:00")
    return hour, minute


def set_routine(graph: Graph, *, crew_id: str, title: str, day, at: str,
                account_id: str, minutes: int = 90, place: str = "",
                source: str = MODULE) -> dict:
    """The same thing, same time, every week."""
    crew_id = str(crew_id or "").strip()
    _require_member(graph, crew_id, account_id)
    title = _text(title)
    if not title:
        # It defaulted to "Wednesday Dawn Patrol Surf Crew", so an empty form told your crew
        # they had a standing surf session.
        raise RoutineError("what is the routine?")
    weekday = _weekday(day)
    hour, minute = _clock(at)
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise RoutineError("length is a number of minutes")
    if not 5 <= minutes <= 24 * 60:
        raise RoutineError("pick a length between 5 minutes and a day")

    session = _sys(graph)
    live = [r for r in session.find_entities("content", {"type": RECORD, "crew_id": crew_id},
                                             limit=100)
            if not r["attrs"].get("ended")]
    if len(live) >= MAX_PER_CREW:
        raise RoutineError(f"that crew already has {MAX_PER_CREW} routines")

    routine_id = session.create_entity("content", {
        "type": RECORD, "crew_id": crew_id, "title": title,
        "weekday": weekday, "hour": hour, "minute": minute,
        "minutes": minutes, "place": _text(place), "set_by": account_id,
        "created_at": now_iso(), "ended": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    reach = len(crews.members(graph, crew_id))
    return {"set": True, "routine_id": routine_id, "crew_id": crew_id, "title": title,
            "recurrence": f"every {DAYS[weekday]} at {hour:02d}:{minute:02d}",
            "upcoming": occurrences(graph, routine_id=routine_id, account_id=account_id,
                                    weeks=4)["dates"],
            # The honest replacement for `synced_calendars: 5`.
            "calendars_synced": 0,
            "can_subscribe": reach,
            "ics_path": f"/v1/crews/{crew_id}/export.ics",
            "sync_note": NOT_SYNCED}


def _routine(graph: Graph, routine_id: str, account_id: str) -> dict:
    row = _sys(graph).get_entity(str(routine_id or "").strip())
    if row is None or row["attrs"].get("type") != RECORD:
        raise RoutineError("no such routine")
    _require_member(graph, row["attrs"].get("crew_id", ""), account_id)
    return row


def _dates(attrs: dict, weeks: int, now=None) -> list[str]:
    """Expand the rule into real dates. This is what makes it more than a sentence."""
    now = now or _now()
    weekday = int(attrs.get("weekday", 0))
    hour, minute = int(attrs.get("hour", 0)), int(attrs.get("minute", 0))
    ahead = (weekday - now.weekday()) % 7
    first = (now + datetime.timedelta(days=ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)
    if first < now:
        first += datetime.timedelta(days=7)
    return [(first + datetime.timedelta(weeks=w)).isoformat() for w in range(weeks)]


def occurrences(graph: Graph, *, routine_id: str, account_id: str,
                weeks: int = DEFAULT_WEEKS, now=None) -> dict:
    row = _routine(graph, routine_id, account_id)
    try:
        weeks = int(weeks)
    except (TypeError, ValueError):
        raise RoutineError("weeks must be a number")
    weeks = max(1, min(weeks, MAX_WEEKS))
    attrs = row["attrs"]
    return {"routine_id": row["id"], "title": attrs.get("title", ""),
            "dates": _dates(attrs, weeks, now), "weeks": weeks,
            "minutes": attrs.get("minutes", 90), "place": attrs.get("place", "")}


def for_crew(graph: Graph, *, crew_id: str, account_id: str, weeks: int = 4,
             now=None) -> dict:
    """Every standing thing this crew does, with its next few dates."""
    crew_id = str(crew_id or "").strip()
    _require_member(graph, crew_id, account_id)
    items = []
    for row in _sys(graph).find_entities("content", {"type": RECORD, "crew_id": crew_id},
                                         limit=100):
        attrs = row["attrs"]
        if attrs.get("ended"):
            continue
        weekday = int(attrs.get("weekday", 0))
        items.append({"routine_id": row["id"], "title": attrs.get("title", ""),
                      "place": attrs.get("place", ""),
                      "recurrence": (f"every {DAYS[weekday]} at "
                                     f"{int(attrs.get('hour', 0)):02d}:"
                                     f"{int(attrs.get('minute', 0)):02d}"),
                      "next": _dates(attrs, max(1, weeks), now)})
    items.sort(key=lambda r: r["next"][0] if r["next"] else "")
    return {"crew_id": crew_id, "routines": items, "empty": not items,
            "calendars_synced": 0,
            "ics_path": f"/v1/crews/{crew_id}/export.ics",
            "sync_note": NOT_SYNCED}


def end(graph: Graph, *, routine_id: str, account_id: str,
        source: str = MODULE) -> dict:
    """Stop it. Whoever set it, or a crew admin."""
    row = _routine(graph, routine_id, account_id)
    attrs = row["attrs"]
    if attrs.get("set_by") != account_id and \
            not crews.is_admin(graph, attrs.get("crew_id", ""), account_id):
        raise RoutineError("only whoever set it, or an admin, can end it")
    if attrs.get("ended"):
        return {"ended": True, "routine_id": row["id"], "already": True}
    _sys(graph).update_entity(row["id"], {"ended": True, "ended_at": now_iso()},
                              source=source)
    return {"ended": True, "routine_id": row["id"]}


def events_for_ics(graph: Graph, crew_id: str, weeks: int = 12, now=None) -> list[dict]:
    """Occurrences shaped for the ICS exporter, so a routine reaches a real calendar.

    This is the only part that makes "synced" mean anything: the crew's existing .ics feed
    picks these up, and a calendar app that subscribes to it sees the standing sessions
    alongside the one-off meets.
    """
    out = []
    for row in _sys(graph).find_entities("content", {"type": RECORD, "crew_id": crew_id},
                                         limit=100):
        attrs = row["attrs"]
        if attrs.get("ended"):
            continue
        minutes = int(attrs.get("minutes", 90) or 90)
        for stamp in _dates(attrs, weeks, now):
            start = datetime.datetime.fromisoformat(stamp)
            # Shaped the way `calendars.export.generate_ics` reads an event — id at the
            # top, everything else under `attrs` — so it needs no special case there.
            out.append({
                "id": f"{row['id']}-{start.date().isoformat()}",
                "attrs": {
                    "title": attrs.get("title", "Crew routine"),
                    "start": start.isoformat(),
                    "end": (start + datetime.timedelta(minutes=minutes)).isoformat(),
                    "location": attrs.get("place", ""),
                    "crew_id": crew_id,
                    "description": "Standing crew routine",
                },
            })
    return out
