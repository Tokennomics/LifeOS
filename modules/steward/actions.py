"""Steward — execute-with-approval. Approving an item turns it into a scheduled task; nothing runs unasked."""

from modules.horizon.planner import week_id
from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write", "tasks:read", "tasks:write", "people:read"}


def open_items(graph: Graph) -> list[dict]:
    session = graph.session("steward", SCOPES)
    return [
        {"id": item["id"], "type": item["attrs"].get("type"), "title": item["attrs"].get("title", ""),
         "suggestion": item["attrs"].get("suggestion", "")}
        for item in session.find_entities("admin_item", {"status": "open"}, limit=100)
    ]


def approve(graph: Graph, item_id: str, source: str = "steward") -> dict:
    session = graph.session("steward", SCOPES)
    item = session.get_entity(item_id)
    if item is None or item["kind"] != "admin_item":
        raise ValueError("unknown admin item")
    a = item["attrs"]
    week = week_id()
    if a.get("type") == "stale_task" and session.get_entity(a.get("ref", "")):
        session.update_entity(a["ref"], {"week": week}, source=source)
        outcome = "scheduled the stale task into this week"
    else:
        title = a.get("title", "admin")
        if a.get("type") == "admin_capture":
            title = f"Handle: {title}"
        session.create_entity(
            "task", {"title": title, "status": "open", "week": week,
                     "if_then": "If it's tomorrow 12:30, then I knock this out in 15 min"},
            source=source,
        )
        outcome = "created a task in this week's plan"
    session.update_entity(item_id, {"status": "approved"}, source=source)
    return {"item_id": item_id, "outcome": outcome}


def dismiss(graph: Graph, item_id: str, source: str = "steward") -> dict:
    session = graph.session("steward", SCOPES)
    item = session.get_entity(item_id)
    if item is None or item["kind"] != "admin_item":
        raise ValueError("unknown admin item")
    session.update_entity(item_id, {"status": "dismissed"}, source=source)
    return {"item_id": item_id, "outcome": "dismissed"}
