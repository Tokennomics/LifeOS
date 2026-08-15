"""The places you have actually been, from your own rows.

`/atlas/living-memory-map` reported 48 memory pins and three "recent geo memories" — a
sunset sketch circle on Calton Hill with Catriona, river surfing at the Eisbachwelle, Bossa
Nova at Miradouro de Santa Catarina — for every account, on an empty database. It also
reported a "Time-Capsule Locked @ Arthur's Seat (Unlocks in 342 days when you revisit with
Alex)": a countdown, to a place you have never been, with a person who does not exist,
implemented nowhere.

The idea is a good one and needs nothing invented: this app already knows where you checked
in, what you reviewed and what you posted. Those are the pins. There is no time capsule,
because nothing implements one, and a locked countdown that never unlocks is worse than no
feature at all.

Coordinates are deliberately absent. Check-ins record a place *name*, not a position — there
is no background location anywhere in this app — so this is a list of places, not a map of
points, and calling it a map would imply a precision that does not exist.
"""

import datetime

from substrate.graph import Graph

MODULE = "personal.atlas"
SCOPES = {"content:read", "places:read"}

MAX_PINS = 200


class AtlasError(ValueError):
    """An atlas that cannot be read."""


def _session(graph: Graph):
    return graph.session(MODULE, SCOPES)


def _sys(graph: Graph):
    from substrate import SYSTEM_OWNER
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _add(pins: dict, place: str, city: str, what: str, stamp: str, kind: str) -> None:
    place = str(place or "").strip()
    if not place:
        return
    key = place.lower()
    pin = pins.setdefault(key, {"place": place, "city": str(city or "").strip(),
                                "memories": [], "first": stamp, "last": stamp})
    pin["memories"].append({"what": what, "when": stamp, "kind": kind})
    if stamp and (not pin["first"] or stamp < pin["first"]):
        pin["first"] = stamp
    if stamp and stamp > pin["last"]:
        pin["last"] = stamp


def pins(graph: Graph, *, account_id: str = "", city: str = "",
         limit: int = MAX_PINS) -> dict:
    """Everywhere you have been, with what happened there."""
    collected: dict = {}

    for row in _session(graph).find_entities("content", {"type": "checkin"}, limit=500):
        attrs = row["attrs"]
        _add(collected, attrs.get("place", ""), attrs.get("city", ""),
             "was here", attrs.get("created_at", ""), "check-in")

    if account_id:
        shared = _sys(graph)
        for row in shared.find_entities("content", {"type": "place_review"}, limit=500):
            attrs = row["attrs"]
            if attrs.get("author_account") != account_id:
                continue
            _add(collected, attrs.get("place", ""), attrs.get("city", ""),
                 attrs.get("text", ""), attrs.get("created_at", ""), "review")
        for row in shared.find_entities("content", {"type": "city_moment"}, limit=500):
            attrs = row["attrs"]
            if attrs.get("account_id") != account_id:
                continue
            _add(collected, attrs.get("city_label") or attrs.get("city", ""),
                 attrs.get("city", ""), attrs.get("caption", ""),
                 attrs.get("created_at", ""), "moment")

    wanted = str(city or "").strip().lower()
    items = [pin for pin in collected.values()
             if not wanted or wanted in (pin["city"] or "").lower()
             or wanted in pin["place"].lower()]
    items.sort(key=lambda p: p["last"], reverse=True)
    for pin in items:
        pin["memories"].sort(key=lambda m: m["when"], reverse=True)
        pin["times"] = len(pin["memories"])

    cities = sorted({pin["city"] for pin in items if pin["city"]})
    return {
        "pins": items[:limit],
        "count": len(items),
        "cities": cities,
        "empty": not items,
        # There is no background location in this app; a check-in is a name you typed.
        "coordinates": False,
        "note": ("Places you named, not positions — nothing here tracks where you are."),
        # `time_capsule_status` counted down 342 days to a capsule at a place the account
        # had never been, with a person who did not exist, implemented nowhere.
        "time_capsule": None,
        "suggestion": ("Nothing pinned yet. Checking in somewhere is what puts it on here."
                       if not items else ""),
    }


def wellness(graph: Graph, *, account_id: str = "", days: int = 30) -> dict:
    """What your last month actually contained. Counts, not indices.

    `/vitals/social-wellness` reported a `flourishing_score` of 92, a `deep_connection_index`
    of 95%, a `real_world_ratio` of "85% Outings / 15% Screen Time" and an `active_crew_size`
    of 18 — every one of them a constant, on any account, including one created a second
    earlier. This app measures no screen time and computes no flourishing.

    What it can honestly say is how many outings, how many places and how many cities, over
    a window it names.
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise AtlasError("days must be a number")
    days = max(1, min(days, 365))
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=days)).isoformat()

    atlas = pins(graph, account_id=account_id)
    recent = [pin for pin in atlas["pins"] if pin["last"] >= since]
    outings = sum(len([m for m in pin["memories"] if m["when"] >= since])
                  for pin in atlas["pins"])

    from modules.social import trust
    vouchers = trust.about(graph, account_id=account_id or "x",
                           subject=account_id)["count"] if account_id else 0

    return {
        "window_days": days,
        "outings": outings,
        "places": len(recent),
        "cities": len({pin["city"] for pin in recent if pin["city"]}),
        "vouched_by": vouchers,
        "empty": outings == 0,
        # The whole of the honest version: no flourishing score, no connection index, and
        # no screen-time ratio for a thing that measures no screens.
        "no_score": ("No wellness score. These are counts of what you recorded, over a "
                     "window you can change — nothing here rates how you are doing."),
        "suggestion": ("Nothing recorded in this window." if outings == 0 else ""),
    }
