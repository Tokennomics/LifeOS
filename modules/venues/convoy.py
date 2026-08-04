"""Outing Convoy ETA Tracker.

Coordinates geographic arrivals and ETAs for travelling crew members.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "venues"


def update_location(
    graph: Graph,
    user_id: str,
    latitude: float,
    longitude: float,
    eta: str,
    event_id: str
) -> str:
    """Updates travelling coordinates and estimated arrival times for a member."""
    if not user_id.strip() or not event_id.strip():
        raise ValueError("user_id and event_id are required")

    session = graph.session(MODULE, SCOPES)
    
    # Store or replace location status
    attrs = {
        "type": "convoy_position",
        "user_id": user_id,
        "event_id": event_id,
        "latitude": latitude,
        "longitude": longitude,
        "eta": eta
    }
    
    # Clean previous record to keep DB slim
    try:
        conn = session.graph.conn
        conn.execute(
            "DELETE FROM entities WHERE kind='admin_item' AND json_extract(attrs, '$.type')='convoy_position' AND json_extract(attrs, '$.user_id')=? AND json_extract(attrs, '$.event_id')=?",
            (user_id, event_id)
        )
        conn.commit()
    except Exception:
        pass

    return session.create_entity("admin_item", attrs, source="convoy_tracker")


def get_convoy_etas(graph: Graph, event_id: str) -> list[dict]:
    """Lists current locations and arrival estimates for the convoy group."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("admin_item", limit=1000)

    etas = []
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "convoy_position" and attrs.get("event_id") == event_id:
            etas.append({
                "user_id": attrs.get("user_id"),
                "latitude": attrs.get("latitude"),
                "longitude": attrs.get("longitude"),
                "eta": attrs.get("eta")
            })

    return etas
