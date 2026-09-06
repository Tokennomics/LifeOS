"""What is actually happening around you — no coordinates, no photos, no invented people.

Two endpoints claimed to render the world near you, and both filled it with strangers who
do not exist.

`/ar/spatial-flares` returned `ar_mode: "ACTIVE_SPATIAL_RADAR"` and three beacons placed in
3D: "☕ Specialty Coffee Meetup" by **Elena R. (96% Match)** at 85 metres on a bearing of 42°,
a venue heatmap at "88% Density", an audio space by "Alex & Crew" — with altitude offsets, as
though the app knew which floor they were on. There is no AR in this app, no compass, and no
position of any kind: a check-in is a place *name* somebody typed. Every number in that
response was decoration on a person who was not there.

`/gallery/live-event-wall` returned two photos by Elena R. and Alex M. with "verified PoP
badges" — `POP-89F12A04` — a proof-of-presence token nobody issued, on no chain, verifying
nothing. There is no image pipeline in this app either; a moment is a caption.

What is real is the same idea with the fiction removed: **the things people have actually
published in this city, that have not expired yet.** On a quiet instance that is nothing,
and saying so is the useful answer — an empty street told honestly is worth more than a busy
one that is invented.

- **No distance, no bearing, no altitude.** Nothing here knows where anybody is standing.
- **No photos.** A moment is a caption, which is what people actually posted.
- **No match percentages and no density scores.** Neither is computed anywhere.
- **Muted people are absent**, the same as everywhere else a city is read.
"""

import datetime

from substrate import SYSTEM_OWNER
from substrate.graph import Graph

from modules.city import chat

MODULE = "city.live"
SCOPES = {"content:read"}

SIGNAL = "synergy_signal"
MOMENT = "city_moment"

MAX_LISTED = 50

NO_POSITION = ("Nothing here knows where anybody is standing. This app stores place names "
               "people typed, never a position — so there is no distance, no bearing and "
               "no radar.")


class LiveError(ValueError):
    """A city that cannot be read."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _live(attrs: dict, now) -> bool:
    if attrs.get("withdrawn"):
        return False
    expires = _parse(attrs.get("expires_at", ""))
    return bool(expires and expires > now)


def _room(city: str) -> str:
    if not str(city or "").strip():
        raise LiveError("which city?")
    return chat.slug(city)


def _nowhere(kind: str) -> dict:
    """The answer when the app does not know where you are.

    `/weather/radar` already answers `needs_city: True` rather than guessing, and guessing
    is how somebody in Porto gets told what is happening in Lisbon. This keeps the shape a
    caller expects so a screen renders empty instead of erroring.
    """
    empty = {"city": "", "count": 0, "empty": True, "needs_city": True,
             "suggestion": "Say which city you are in and this fills up."}
    if kind == "around":
        return {**empty, "live": [], "coordinates": False,
                "augmented_reality": False, "no_position": NO_POSITION}
    return {**empty, "posts": [], "photos": False, "verified_presence": False,
            "note": "Captions, not photos — nothing in this app stores an image."}


def around(graph: Graph, city: str, *, viewer_id: str = "",
           limit: int = MAX_LISTED) -> dict:
    """Everything live in a city right now: what people are up for, and what they posted.

    The replacement for the AR radar. Same question — "what is happening near me" — answered
    from rows instead of from three hardcoded strangers with bearings attached.
    """
    if not str(city or "").strip():
        return _nowhere("around")
    room = _room(city)
    now = _now()
    session = _sys(graph)
    hidden = chat.muted_by(graph, viewer_id) if viewer_id else set()

    items = []
    for row in session.find_entities("content", {"type": SIGNAL, "city": room},
                                     limit=MAX_LISTED * 4):
        attrs = row["attrs"]
        if not _live(attrs, now) or attrs.get("account_id") in hidden:
            continue
        items.append({
            "kind": "up for it",
            "id": row["id"],
            "what": attrs.get("activity") or f"{attrs.get('offers', '')} for "
                                             f"{attrs.get('wants', '')}".strip(),
            "note": attrs.get("note", ""),
            "handle": attrs.get("handle") or "someone",
            "mine": attrs.get("account_id") == viewer_id,
            "created_at": attrs.get("created_at", ""),
        })

    for row in session.find_entities("content", {"type": MOMENT, "city": room},
                                     limit=MAX_LISTED * 4):
        attrs = row["attrs"]
        if not _live(attrs, now) or attrs.get("account_id") in hidden:
            continue
        items.append({
            "kind": "posted",
            "id": row["id"],
            "what": attrs.get("caption", ""),
            "note": "",
            "handle": attrs.get("handle") or "someone",
            "mine": attrs.get("account_id") == viewer_id,
            "created_at": attrs.get("created_at", ""),
        })

    items.sort(key=lambda i: i["created_at"], reverse=True)
    return {
        "city": room,
        "live": items[:limit],
        "count": len(items),
        "empty": not items,
        "needs_city": False,
        # Every one of these was in the response this replaces.
        "coordinates": False,
        "augmented_reality": False,
        "no_position": NO_POSITION,
        "suggestion": ("Nothing is live here right now. Publishing what you are up for is "
                       "what puts something on this." if not items else ""),
    }


def wall(graph: Graph, city: str, *, viewer_id: str = "",
         limit: int = MAX_LISTED) -> dict:
    """What people posted in this city, before it expires.

    The replacement for the photo wall. There is no image pipeline in this app and never
    was, so a moment is a caption — and the "verified PoP badges" attached to the two
    invented photos were tokens nobody issued, verifying nothing.
    """
    if not str(city or "").strip():
        return _nowhere("wall")
    room = _room(city)
    now = _now()
    hidden = chat.muted_by(graph, viewer_id) if viewer_id else set()

    posts = []
    for row in _sys(graph).find_entities("content", {"type": MOMENT, "city": room},
                                         limit=MAX_LISTED * 4):
        attrs = row["attrs"]
        if not _live(attrs, now) or attrs.get("account_id") in hidden:
            continue
        posts.append({"id": row["id"], "caption": attrs.get("caption", ""),
                      "handle": attrs.get("handle") or "someone",
                      "mine": attrs.get("account_id") == viewer_id,
                      "created_at": attrs.get("created_at", "")})
    posts.sort(key=lambda p: p["created_at"], reverse=True)
    return {
        "city": room,
        "posts": posts[:limit],
        "count": len(posts),
        "empty": not posts,
        "needs_city": False,
        # There is no image pipeline here, and nothing mints a proof of presence.
        "photos": False,
        "verified_presence": False,
        "note": ("Captions, not photos — nothing in this app stores an image. Nothing is "
                 "minted and nobody is verified as having been anywhere."),
        "suggestion": ("Nothing posted here yet." if not posts else ""),
    }
