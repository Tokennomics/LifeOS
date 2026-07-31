"""Geographic Event Activity Heatmap Engine.

Aggregates local events and computes coordinate intensity weights based on attendance.
"""

from substrate.graph import Graph

SCOPES = {"events:read"}
MODULE = "venues"


def get_activity_heatmap(graph: Graph) -> list[dict]:
    """Retrieves event coordinates and calculates intensity weights by RSVP counts."""
    session = graph.session(MODULE, SCOPES)
    
    events = session.find_entities("event", limit=500)
    hotspots = []

    for ev in events:
        attrs = ev.get("attrs", {})
        lat = attrs.get("lat")
        lng = attrs.get("lng")
        
        # We need valid coordinates to map the event
        if lat is not None and lng is not None:
            # Determine weight based on attending list or mock attendance
            rsvps = attrs.get("attending", [])
            rsvp_count = len(rsvps) if isinstance(rsvps, list) else int(attrs.get("rsvp_count", 1))
            
            # Base weight is 1.0, scales with attendance density
            weight = max(1.0, float(rsvp_count))
            
            hotspots.append({
                "event_id": ev["id"],
                "title": attrs.get("title", "Unnamed Event"),
                "lat": float(lat),
                "lng": float(lng),
                "weight": weight
            })

    return hotspots
