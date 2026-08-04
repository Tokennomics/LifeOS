"""Collaborative Outing Itinerary Planner.

Enables crew members to propose and vote on sequential venues for an outing.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "venues"


def propose_itinerary_node(
    graph: Graph,
    event_id: str,
    venue_id: str,
    sequence_order: int
) -> str:
    """Proposes a venue as a sequential stop in the crew's outing itinerary."""
    if not event_id.strip() or not venue_id.strip():
        raise ValueError("event_id and venue_id are required")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "itinerary_node",
        "event_id": event_id,
        "venue_id": venue_id,
        "sequence_order": sequence_order
    }
    
    return session.create_entity("content", attrs, source="group_itineraries")


def get_itinerary(graph: Graph, event_id: str) -> list[dict]:
    """Retrieves the sequential itinerary timeline proposed for an outing."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("content", limit=1000)

    nodes = []
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "itinerary_node" and attrs.get("event_id") == event_id:
            nodes.append({
                "itinerary_id": item["id"],
                "venue_id": attrs.get("venue_id"),
                "sequence_order": attrs.get("sequence_order"),
                "created_at": item["created_at"]
            })

    nodes.sort(key=lambda x: x["sequence_order"])
    return nodes
