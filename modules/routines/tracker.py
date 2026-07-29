"""Habit Stacking & Routine Consistency Loop.

Builds atomic routines (trigger -> micro-action -> goal connection), tracks streak
consistency, and publishes routine.completed events.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"content:read", "content:write"}
MODULE = "routines"


def create_routine(graph: Graph, name: str, trigger: str, time_of_day: str = "morning",
                   items: list[str] | None = None, source: str = MODULE) -> dict:
    """Creates a new routine entity in the graph."""
    if not name.strip():
        raise ValueError("routine name required")

    session = graph.session(MODULE, SCOPES)
    routine_id = session.create_entity(
        "content",
        {
            "type": "routine",
            "name": name.strip(),
            "trigger": trigger.strip(),
            "time_of_day": time_of_day,
            "items": items or [],
            "streak": 0,
            "last_completed": "",
        },
        source=source,
    )
    return {"routine_id": routine_id, "name": name, "streak": 0}


def log_routine_completion(graph: Graph, routine_id: str, source: str = MODULE) -> dict:
    """Logs completion for a routine and increments streak."""
    session = graph.session(MODULE, SCOPES)
    entity = session.get_entity(routine_id)
    if not entity or entity.get("kind") != "content" or entity.get("attrs", {}).get("type") != "routine":
        raise ValueError(f"routine '{routine_id}' not found")

    attrs = entity.get("attrs", {})
    current_streak = attrs.get("streak", 0) + 1
    now_iso = datetime.now(timezone.utc).isoformat()

    attrs["streak"] = current_streak
    attrs["last_completed"] = now_iso
    session.update_entity(routine_id, attrs, source=source)

    graph.bus.publish("routine.completed", {"routine_id": routine_id, "streak": current_streak, "module": MODULE})
    return {"routine_id": routine_id, "name": attrs.get("name"), "streak": current_streak, "last_completed": now_iso}


def get_routines_status(graph: Graph) -> list[dict]:
    """Lists all active routines and their current streak status."""
    session = graph.session(MODULE, SCOPES)
    routines = session.find_entities("content", {"type": "routine"}, limit=100)

    res = []
    for r in routines:
        attrs = r.get("attrs", {})
        res.append({
            "routine_id": r["id"],
            "name": attrs.get("name", "Untitled Routine"),
            "trigger": attrs.get("trigger", ""),
            "time_of_day": attrs.get("time_of_day", "morning"),
            "items": attrs.get("items", []),
            "streak": attrs.get("streak", 0),
            "last_completed": attrs.get("last_completed", ""),
        })
    return res
