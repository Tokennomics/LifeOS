"""Where a group is meeting, and what is actually known about who is on their way.

`POST /routing/group-nav` reported `navigation_active: True`, four waypoints, six members
"synced on route", a live sync interval of 1.5s and `next_turn: "Turn left at Miradouro de
Santa Luzia in 80m"` — for a route name it took from the request body, on an app that has
never held a coordinate. There is no routing engine here, no map matching, no positions and
no six members: the number was a literal.

What is real is the meetup: a place name somebody typed, a start time, and the list of who
said they are going. And one further fact — whether each of those people has announced they
are in the city (`city/arrival.py`), which is a public row they created themselves.

- **`routing: False`.** Not "unavailable right now": there is no engine and no position to
  route from, and a client must not render a turn card.
- **No distances, no bearings, no ETAs.** City granularity is the promise the whole city
  surface makes, and this endpoint is exactly where somebody would be tempted to break it.
- **A check-in is private.** `social.signals.check_in` writes into the caller's own slice on
  purpose, so "has Ana arrived" is not a question this module can answer about Ana, and it
  says so rather than reporting `arrived: False` — which reads as "she is not there yet".
  Your own check-in for this meetup is yours to see, so that one is included.
- **The place name is the useful part.** Handing it back so it can be searched in whatever
  maps app somebody already has is worth more than a fabricated turn.
"""

from substrate import SYSTEM_OWNER
from substrate.graph import Graph

from modules.city import arrival, meetups
from modules.social import signals

MODULE = "city.navigation"
SCOPES = {"content:read"}

NO_ROUTING = ("There is no routing engine in this app and no position for anybody. The "
              "place name is the whole answer — search it in whatever maps app you use.")
NO_TRACKING = ("Who has arrived is not something this app knows. A check-in is private to "
               "whoever made it, so nobody is reported as on their way or late.")


class NavigationError(ValueError):
    """A meetup that cannot be looked up."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _meetup(graph: Graph, meetup_id: str) -> dict:
    meetup_id = str(meetup_id or "").strip()
    if not meetup_id:
        raise NavigationError("which meetup? pass `meetup_id`")
    row = _sys(graph).get_entity(meetup_id)
    if row is None or row["attrs"].get("type") != meetups.RECORD:
        raise NavigationError("unknown meetup")
    return row


def _my_checkin(graph: Graph, meetup_id: str) -> dict:
    """The caller's own check-in for this meetup, if they made one.

    Read out of the caller's own slice — `graph` is already scoped to them — because that
    is where `signals.check_in` puts it. Nobody else's is reachable from here, which is the
    point: this is the one arrival fact the app can honestly report, and it is your own.
    """
    try:
        rows = graph.session(MODULE, SCOPES).find_entities(
            "content", {"type": signals.CHECKIN, "meetup_id": meetup_id}, limit=5)
    except Exception:
        return {}
    if not rows:
        return {}
    row = rows[-1]
    return {"checkin_id": row["id"], "created_at": row["attrs"].get("created_at", ""),
            "place": row["attrs"].get("place", "")}


def where(graph: Graph, meetup_id: str, *, viewer_id: str = "") -> dict:
    """The meeting point and who said they are coming. No route, because there is none."""
    row = _meetup(graph, meetup_id)
    attrs = row["attrs"]
    city = attrs.get("city", "")

    in_city = set()
    if city:
        try:
            in_city = {person["account_id"]
                       for person in arrival.around(graph, city, viewer_id=viewer_id)}
        except Exception:
            in_city = set()

    handles = dict(attrs.get("handles") or {})
    going = [{"account_id": person,
              "handle": handles.get(person) or "someone",
              # A public row they wrote themselves, and the only shared statement about
              # whereabouts this app has. Absent means they have not announced, which is
              # not the same as "not here".
              "announced_in_city": person in in_city,
              "you": person == viewer_id}
             for person in (attrs.get("going") or [])]

    place = attrs.get("place", "")
    mine = _my_checkin(graph, row["id"]) if viewer_id else {}

    return {
        "meetup_id": row["id"], "title": attrs.get("title", ""),
        "city": city, "place": place, "starts_at": attrs.get("starts_at", ""),
        "cancelled": bool(attrs.get("cancelled")),
        "going": going, "going_count": len(going),
        "you_checked_in": bool(mine), "your_checkin_at": mine.get("created_at", ""),
        "routing": False, "no_routing": NO_ROUTING, "no_tracking": NO_TRACKING,
        "coordinates": False,
        "safety_note": meetups.SAFETY_NOTE,
        "suggestion": (f"Search '{place}' in your maps app." if place else
                       "This meetup has no place written on it — ask the organiser where, "
                       "and it belongs in the meetup's `place`."),
    }
