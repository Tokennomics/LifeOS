"""P2P Shared Outing Photo Gallery.

Allows crew members to associate shared photo links and assets with outing events.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "comms"


def upload_photo(
    graph: Graph,
    event_id: str,
    owner_id: str,
    photo_url: str
) -> str:
    """Registers a photo link associated with a specific outing event."""
    if not event_id.strip() or not photo_url.strip():
        raise ValueError("event_id and photo_url are required")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "shared_photo",
        "event_id": event_id,
        "owner_id": owner_id,
        "photo_url": photo_url
    }
    
    return session.create_entity("content", attrs, source="photo_gallery")


def list_photos(graph: Graph, event_id: str) -> list[dict]:
    """Retrieves all photos registered under an outing event."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("content", limit=1000)

    photos = []
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "shared_photo" and attrs.get("event_id") == event_id:
            photos.append({
                "photo_id": item["id"],
                "owner_id": attrs.get("owner_id"),
                "photo_url": attrs.get("photo_url"),
                "created_at": item["created_at"]
            })

    return photos
