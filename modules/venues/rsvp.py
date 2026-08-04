"""P2P Outing RSVP Manager.

Tracks attendee RSVPs and responses for planned outings.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "venues"


def submit_rsvp(
    graph: Graph,
    event_id: str,
    user_id: str,
    status: str
) -> str:
    """Logs or updates an RSVP response for a crew outing event."""
    if not event_id.strip() or not user_id.strip():
        raise ValueError("event_id and user_id are required")
    if status not in {"accepted", "declined", "tentative"}:
        raise ValueError("invalid status value")

    session = graph.session(MODULE, SCOPES)
    
    # Store RSVP as an admin_item
    attrs = {
        "type": "outing_rsvp",
        "event_id": event_id,
        "user_id": user_id,
        "status": status
    }
    
    return session.create_entity("admin_item", attrs, source="rsvp_manager")


def list_rsvps(graph: Graph, event_id: str) -> list[dict]:
    """Retrieves all RSVPs registered for a given outing event."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("admin_item", limit=1000)
    
    rsvps = []
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "outing_rsvp" and attrs.get("event_id") == event_id:
            rsvps.append({
                "rsvp_id": item["id"],
                "user_id": attrs.get("user_id"),
                "status": attrs.get("status")
            })
            
    return rsvps
