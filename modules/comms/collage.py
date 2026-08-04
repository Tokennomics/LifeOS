"""Live Crew Photo Collage Creator.

Aggregates outing gallery photos and memory capsules into structured collages.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "comms"


def create_photo_collage(
    graph: Graph,
    event_id: str
) -> list[dict]:
    """Generates a structured collage layout representation of outing photo URLs."""
    session = graph.session(MODULE, SCOPES)
    
    # Query all gallery entities
    items = session.find_entities("content", limit=1000)
    photos = []
    
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "gallery_photo" and attrs.get("event_id") == event_id:
            photos.append({
                "photo_id": item["id"],
                "url": attrs.get("photo_url"),
                "owner_id": attrs.get("owner_id"),
                "created_at": item["created_at"]
            })

    # Sort photos chronologically
    photos.sort(key=lambda x: x["created_at"])
    return photos
