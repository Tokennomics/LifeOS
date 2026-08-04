"""Memento — capsules: collect your life, not monsters.

Drop a memory at a place; it locks. Come back within the unlock radius and it opens.
Digital is glue; the physical world is the product (Law 5).
"""

import datetime

from modules.memento.geo import haversine_m
from substrate.graph import Graph

SCOPES = {"memories:read", "memories:write", "places:read", "places:write", "events:read"}
DEFAULT_RADIUS_M = 75.0


def drop(graph: Graph, text: str, lat: float, lon: float, place_name: str = "",
         radius_m: float = DEFAULT_RADIUS_M, event_id: str = "", source: str = "memento") -> dict:
    if not text.strip():
        raise ValueError("a capsule needs some words")
    session = graph.session("memento", SCOPES)
    name = place_name.strip() or f"{lat:.4f},{lon:.4f}"
    existing = session.find_entities("place", {"name": name}, limit=1)
    place_id = existing[0]["id"] if existing else session.create_entity(
        "place", {"name": name, "lat": lat, "lon": lon}, source=source,
    )
    attrs = {"type": "capsule", "text": text, "lat": lat, "lon": lon, "radius_m": radius_m,
             "locked": True, "dropped_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if event_id:
        attrs["event_id"] = event_id  # completes the Memento quest for that Convoy event
    capsule_id = session.create_entity("memory", attrs, source=source)
    session.create_edge(capsule_id, place_id, "located_at", source=source)
    graph.bus.publish("capsule.dropped", {"capsule_id": capsule_id, "place": name, "module": "memento"})
    return {"capsule_id": capsule_id, "place": name}


def nearby(graph: Graph, lat: float | None = None, lon: float | None = None,
           limit: int = 50) -> list[dict]:
    """All capsules; with coordinates given, sorted by distance. Locked capsules hide their text."""
    session = graph.session("memento", SCOPES)
    out = []
    for capsule in session.find_entities("memory", {"type": "capsule"}, limit=200):
        a = capsule["attrs"]
        item = {"id": capsule["id"], "locked": a.get("locked", True),
                "lat": a.get("lat", 0.0), "lon": a.get("lon", 0.0),
                "dropped_at": a.get("dropped_at", ""), "radius_m": a.get("radius_m", DEFAULT_RADIUS_M)}
        place = session.neighbors(capsule["id"], rel="located_at", direction="out")
        item["place"] = place[0]["attrs"].get("name", "?") if place else "?"
        if lat is not None and lon is not None:
            item["distance_m"] = round(haversine_m(lat, lon, a.get("lat", 0.0), a.get("lon", 0.0)))
        if not item["locked"]:
            item["text"] = a.get("text", "")
        out.append(item)
    out.sort(key=lambda c: c.get("distance_m", 1e12))
    return out[:limit]


def unlock(graph: Graph, lat: float, lon: float, source: str = "memento") -> dict:
    """Unlock every locked capsule whose radius covers the given position."""
    session = graph.session("memento", SCOPES)
    opened = []
    for capsule in session.find_entities("memory", {"type": "capsule"}, limit=200):
        a = capsule["attrs"]
        if not a.get("locked", True):
            continue
        if haversine_m(lat, lon, a.get("lat", 0.0), a.get("lon", 0.0)) <= a.get("radius_m", DEFAULT_RADIUS_M):
            session.update_entity(capsule["id"], {"locked": False}, source=source)
            opened.append({"id": capsule["id"], "text": a.get("text", "")})
    return {"unlocked": len(opened), "capsules": opened}
