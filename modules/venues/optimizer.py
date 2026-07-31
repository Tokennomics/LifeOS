"""Outing Route Optimizer.

Calculates the most optimal order to visit venues during a crew outing.
"""

import math
from substrate.graph import Graph

SCOPES = {"events:read", "places:read"}
MODULE = "venues"


def _distance(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


def optimize_outing_route(graph: Graph, place_ids: list[str]) -> list[dict]:
    """Sorts places using a greedy nearest-neighbor approach from the first venue."""
    if not place_ids:
        return []

    session = graph.session(MODULE, SCOPES)
    places = []
    
    for pid in place_ids:
        try:
            ent = session.get_entity(pid)
            if ent:
                places.append(ent)
            else:
                # Fallback mock details if not in graph
                places.append({
                    "id": pid,
                    "kind": "place",
                    "attrs": {"name": f"Place {pid}", "lat": 0.0, "lng": 0.0}
                })
        except Exception:
            places.append({
                "id": pid,
                "kind": "place",
                "attrs": {"name": f"Place {pid}", "lat": 0.0, "lng": 0.0}
            })

    optimized = []
    current = places[0]
    optimized.append({
        "place_id": current["id"],
        "name": current.get("attrs", {}).get("name", "Unnamed Venue"),
        "lat": current.get("attrs", {}).get("lat", 0.0),
        "lng": current.get("attrs", {}).get("lng", 0.0)
    })
    remaining = places[1:]

    while remaining:
        curr_lat = current.get("attrs", {}).get("lat", 0.0)
        curr_lon = current.get("attrs", {}).get("lng", 0.0)
        
        best_idx = 0
        best_dist = float("inf")
        
        for idx, item in enumerate(remaining):
            lat = item.get("attrs", {}).get("lat", 0.0)
            lon = item.get("attrs", {}).get("lng", 0.0)
            d = _distance(curr_lat, curr_lon, lat, lon)
            if d < best_dist:
                best_dist = d
                best_idx = idx

        current = remaining.pop(best_idx)
        optimized.append({
            "place_id": current["id"],
            "name": current.get("attrs", {}).get("name", "Unnamed Venue"),
            "lat": current.get("attrs", {}).get("lat", 0.0),
            "lng": current.get("attrs", {}).get("lng", 0.0)
        })

    return optimized
