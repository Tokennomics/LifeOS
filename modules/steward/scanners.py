"""Steward — proactive life-admin detection. Watches the graph, not an inbox (P0).

Scanners (deterministic, no external access; email/calendar OAuth scanners join later):
  stale_task      open task, unscheduled, older than 14 days -> decide: do or drop
  admin_capture   captured thought containing admin keywords -> turn into action
  reconnect       person overdue past 2x cadence -> schedule the reconnect

Every finding is an admin_item entity; approve/dismiss in actions.py.
"""

import datetime

from modules.horizon.planner import week_id
from modules.reconnect import decay
from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write", "tasks:read", "content:read", "people:read"}
KEYWORDS = ("renew", "bill", "cancel", "book", "appointment", "pay", "insurance",
            "subscription", "invoice", "tax", "register", "rego", "licence", "license")
STALE_DAYS = 14


def _age_days(iso: str, now: datetime.datetime) -> float:
    try:
        return (now - datetime.datetime.fromisoformat(iso)).total_seconds() / 86400
    except (ValueError, TypeError):
        return 0.0


def scan(graph: Graph, source: str = "steward-scan") -> dict:
    session = graph.session("steward", SCOPES)
    now = datetime.datetime.now(datetime.timezone.utc)
    week = week_id(now)
    created = 0

    def emit(item_type: str, ref: str, title: str, suggestion: str) -> None:
        nonlocal created
        if session.find_entities("admin_item", {"ref": ref, "status": "open"}, limit=1):
            return  # already surfaced and still open
        session.create_entity(
            "admin_item",
            {"type": item_type, "ref": ref, "title": title, "suggestion": suggestion, "status": "open"},
            source=source,
        )
        graph.bus.publish("admin.detected", {"type": item_type, "ref": ref, "module": "steward"})
        created += 1

    for task in session.find_entities("task", {"status": "open"}, limit=200):
        a = task["attrs"]
        if a.get("week") == week:
            continue
        if _age_days(task["created_at"], now) >= STALE_DAYS:
            emit("stale_task", task["id"], a.get("title", "?"),
                 "Stale for 2+ weeks. Approve to schedule it this week, or dismiss to let it go.")

    for content in session.find_entities("content", {"type": "capture"}, limit=200):
        text = content["attrs"].get("text", "")
        if _age_days(content["created_at"], now) <= 30 and any(k in text.lower() for k in KEYWORDS):
            emit("admin_capture", content["id"], text[:80],
                 "Looks like life admin hiding in a capture. Approve to make it a task this week.")

    for person in decay.ranked(graph, limit=50):
        if person["overdue"] >= 2.0:
            emit("reconnect", person["id"], f"Reconnect with {person['name']}",
                 f"{person['days_since']:.0f} days since contact (cadence {person['cadence_days']}d). "
                 f"Approve to schedule it this week.")

    return {"created": created, "open": len(session.find_entities("admin_item", {"status": "open"}, limit=200))}
