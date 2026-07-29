"""Parked Idea Promotion & Distraction Sink Sorter.

Manages distraction-sink parked project ideas and promotes them into active
goals or tasks once current gate/focused goals pass.
"""

from modules.horizon.planner import week_id
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "goals:read", "goals:write", "tasks:read", "tasks:write"}


def list_parked(graph: Graph) -> list[dict]:
    """Lists all open parked project ideas in the graph."""
    session = graph.session("horizon", SCOPES)
    items = session.find_entities("content", {"type": "parked_idea"}, limit=200)
    return [
        {
            "id": item["id"],
            "text": item.get("attrs", {}).get("text", ""),
            "status": item.get("attrs", {}).get("status", "parked"),
            "created_at": item.get("created_at", ""),
        }
        for item in items
        if item.get("attrs", {}).get("status", "parked") == "parked"
    ]


def promote_parked(graph: Graph, idea_id: str, target_level: str = "goal", source: str = "parked_sorter") -> dict:
    """Promotes a parked project idea into an active goal or task."""
    session = graph.session("horizon", SCOPES)
    idea = session.get_entity(idea_id)
    if idea is None or idea["kind"] != "content" or idea["attrs"].get("type") != "parked_idea":
        raise ValueError(f"Parked idea entity not found: {idea_id}")

    text = idea["attrs"].get("text", "Parked Idea")
    created_id = None

    if target_level == "goal":
        created_id = session.create_entity(
            "goal",
            {"title": text, "level": "goal", "focus": False},
            source=source,
        )
        outcome = f"Promoted parked idea '{text}' to an active Goal"
    elif target_level == "task":
        current_w = week_id()
        created_id = session.create_entity(
            "task",
            {"title": text, "status": "open", "week": current_w},
            source=source,
        )
        outcome = f"Promoted parked idea '{text}' to a Task in week {current_w}"
    else:
        raise ValueError("target_level must be 'goal' or 'task'")

    # Mark parked idea as promoted
    session.update_entity(idea_id, {"status": "promoted", "promoted_to": created_id}, source=source)

    return {
        "idea_id": idea_id,
        "target_level": target_level,
        "created_id": created_id,
        "outcome": outcome,
    }
