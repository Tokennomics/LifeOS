"""Routine Milestones & Badges.

Tracks and enqueues rewarding badges and routine consistency achievements.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


def award_milestone(
    graph: Graph,
    user_id: str,
    title: str,
    description: str
) -> str:
    """Awards a milestone badge to a user for routine accomplishments."""
    if not user_id.strip() or not title.strip():
        raise ValueError("user_id and title are required")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "routine_milestone",
        "user_id": user_id,
        "title": title,
        "description": description
    }
    
    return session.create_entity("admin_item", attrs, source="milestones")


def list_milestones(graph: Graph, user_id: str) -> list[dict]:
    """Retrieves all awarded milestone achievements for a user."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("admin_item", limit=1000)

    milestones = []
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "routine_milestone" and attrs.get("user_id") == user_id:
            milestones.append({
                "milestone_id": item["id"],
                "title": attrs.get("title"),
                "description": attrs.get("description"),
                "created_at": item["created_at"]
            })

    return milestones
