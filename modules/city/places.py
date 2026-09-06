"""Third places — the map a city has before it has any users.

This is the honest half of the cold-start problem. `city.arrival` composes crews, events and
who is around, and on a new instance every one of those is empty; the suggestion it prints
is "start something", which is true and is also a lot to ask of somebody who landed two
hours ago. A directory of real places is the one thing a city can have on day zero without a
single user, because it comes from a map the world already maintains.

`/seeding/third-places-directory` claimed to have done this: "160 Verified Third Places",
broken down to 42 specialty coffee workspaces, with a `live_status` of "100% OPERATIONAL
(Live Opening Hours & Wi-Fi Speeds Verified)". Nothing was stored and the same numbers came
back for every city. This module actually stores them, from OpenStreetMap, and claims
nothing OSM does not say.

Design follows the venue-feed precedent exactly, because a place is the same kind of object
as a listing:

- **System-owned and public.** A café is not anybody's private row, and the whole point is
  that a person who has just arrived can see it before they have added anything.
- **Deduped by OSM id**, so re-seeding a city updates rather than doubles it. Seeding is
  idempotent by construction — an operator running it twice is the expected case, not a bug
  report.
- **Refreshable, not accumulating.** A place that has vanished from OSM stays until it is
  explicitly pruned; disappearing rows on a refresh would silently delete a café because a
  volunteer's edit was mid-review.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat
from modules.feeds.providers import openmeteo, overpass

MODULE = "city.places"
SCOPES = {"content:read", "content:write"}
RECORD = "city_place"

MAX_LISTED = 100
MAX_PER_CATEGORY = 60


class PlacesError(ValueError):
    """A city that cannot be seeded, or a category that does not exist."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def categories() -> list[str]:
    return overpass.categories()


def locate(city: str, *, fetch=None) -> dict:
    """Where a city is, from the geocoder rather than from a hardcoded table.

    The endpoint this replaces had two cities in an if/else — Munich and Edinburgh — and
    everything else silently got Edinburgh's coordinates.
    """
    found = openmeteo.geocode(city, fetch=fetch)
    if found["status"] != "ok" or not found["places"]:
        return {"status": found["status"], "city": city}
    best = found["places"][0]
    return {"status": "ok", "city": city, "lat": best["lat"], "lon": best["lon"],
            "resolved": best["name"], "country": best.get("country", ""),
            "timezone": best.get("timezone", "")}


def seed(graph: Graph, city: str, *, category: str = "", radius_m: int = 4000,
         lat: float | None = None, lon: float | None = None,
         geocode_fetch=None, overpass_fetch=None, source: str = MODULE) -> dict:
    """Pull a city's third places into the graph.

    One category at a time by default, or all of them when none is named — an operator
    seeding a new city wants the second, and a scheduled refresh wants the first. Every
    category is reported separately so one Overpass timeout does not read as an empty city.
    """
    if not str(city or "").strip():
        raise PlacesError("which city?")
    room = chat.slug(city)

    if lat is None or lon is None:
        where = locate(city, fetch=geocode_fetch)
        if where["status"] != "ok":
            # `verified` is on both exits deliberately: a caller checking whether this
            # data is independently verified must get the same answer whether the seed
            # succeeded or the geocoder was unreachable.
            return {"city": room, "status": where["status"], "added": 0, "updated": 0,
                    "categories": {}, "verified": False,
                    "attribution": "© OpenStreetMap contributors",
                    "detail": "could not place this city on the map, so nothing was asked for"}
        lat, lon = where["lat"], where["lon"]

    wanted = [category] if category else categories()
    for name in wanted:
        if name not in CATEGORY_SET:
            raise PlacesError(f"unknown category {name!r} (known: {categories()})")

    session = _sys(graph)
    added = updated = 0
    per_category = {}
    for name in wanted:
        result = overpass.search(lat, lon, name, radius_m, fetch=overpass_fetch)
        if result["status"] != "ok":
            per_category[name] = {"status": result["status"], "added": 0, "updated": 0}
            continue
        cat_added = cat_updated = 0
        for item in result["items"][:MAX_PER_CATEGORY]:
            attrs = {
                "type": RECORD, "city": room,
                "city_label": str(city or "").strip()[:80],
                "osm_id": item["osm_id"], "name": item["name"],
                "category": item["category"], "lat": item["lat"], "lon": item["lon"],
                "opening_hours": item.get("opening_hours", ""),
                "website": item.get("website", ""),
                "street": item.get("street", ""),
                "wheelchair": item.get("wheelchair", ""),
                "refreshed_at": now_iso(),
            }
            existing = session.find_entities(
                "content", {"type": RECORD, "osm_id": item["osm_id"]}, limit=1)
            if existing:
                session.update_entity(existing[0]["id"], attrs, source=source)
                cat_updated += 1
            else:
                session.create_entity("content", {**attrs, "created_at": now_iso()},
                                      source=source, owner_id=SYSTEM_OWNER)
                cat_added += 1
        per_category[name] = {"status": "ok", "added": cat_added, "updated": cat_updated}
        added += cat_added
        updated += cat_updated

    return {"city": room, "status": "ok", "added": added, "updated": updated,
            "categories": per_category,
            # The claim the old endpoint made and could not support.
            "verified": False,
            "note": ("From OpenStreetMap. Opening hours appear only where OSM has them; "
                     "nothing here is independently verified."),
            "attribution": "© OpenStreetMap contributors"}


CATEGORY_SET = set(overpass.categories())


def listing(graph: Graph, city: str, *, category: str = "",
            limit: int = MAX_LISTED) -> dict:
    """What is in this city. The read side, and the one a new arrival actually hits."""
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise PlacesError("which city?")
    query = {"type": RECORD, "city": room}
    if category:
        query["category"] = category

    rows = _sys(graph).find_entities("content", query, limit=MAX_LISTED * 4)
    places = []
    for row in rows:
        attrs = row["attrs"]
        place = {"place_id": row["id"], "name": attrs.get("name", ""),
                 "category": attrs.get("category", ""),
                 "lat": attrs.get("lat"), "lon": attrs.get("lon")}
        for field in ("opening_hours", "website", "street", "wheelchair"):
            if attrs.get(field):
                place[field] = attrs[field]
        places.append(place)
    places.sort(key=lambda p: (p["category"], p["name"]))

    breakdown = {}
    for place in places:
        breakdown[place["category"]] = breakdown.get(place["category"], 0) + 1

    return {"city": room, "places": places[:limit], "total": len(places),
            "breakdown": breakdown, "empty": not places,
            "attribution": "© OpenStreetMap contributors",
            "suggestion": "" if places else (
                "This city has not been seeded yet. An operator can run "
                "`POST /v1/seeding/third-places-directory` for it."),
            }


def prune(graph: Graph, city: str, *, older_than_days: int = 90,
          source: str = MODULE) -> dict:
    """Drop places that have not been seen in a refresh for a long time.

    Explicit rather than automatic on every seed: a café should not vanish from the app
    because one Overpass query timed out, which is what "delete anything not in this
    response" would do.
    """
    room = chat.slug(city)
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=max(1, int(older_than_days)))).isoformat()
    session = _sys(graph)
    removed = 0
    for row in session.find_entities("content", {"type": RECORD, "city": room}, limit=2000):
        if str(row["attrs"].get("refreshed_at", "")) < cutoff:
            session.delete_entity(row["id"], source=source)
            removed += 1
    return {"city": room, "removed": removed}
