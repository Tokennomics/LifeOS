"""P2P Outing Group Announcement Board.

Publishes pinned notices and crew-wide notifications.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "comms"


def publish_bulletin(
    graph: Graph,
    crew_id: str,
    title: str,
    body: str
) -> str:
    """Publishes a new announcement board bulletin pinned to a crew."""
    if not crew_id.strip() or not title.strip():
        raise ValueError("crew_id and title are required")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "bulletin_announcement",
        "crew_id": crew_id,
        "title": title,
        "body": body
    }
    
    return session.create_entity("content", attrs, source="bulletins")


def list_bulletins(graph: Graph, crew_id: str) -> list[dict]:
    """Lists all active bulletins pinned to a target crew."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("content", limit=1000)

    bulletins = []
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "bulletin_announcement" and attrs.get("crew_id") == crew_id:
            bulletins.append({
                "bulletin_id": item["id"],
                "title": attrs.get("title"),
                "body": attrs.get("body"),
                "created_at": item["created_at"]
            })

    return bulletins
