"""Habit Streak Risk Nudge Engine.

Pushes notification alerts when a habit completion streak is about to break.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


def trigger_streak_nudges(graph: Graph) -> list[dict]:
    """Scans pending habit streaks and enqueues warning notifications."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("admin_item", limit=500)
    
    triggered = []

    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "routine_streak" or "streak" in attrs:
            streak = attrs.get("streak", 0)
            completed_today = attrs.get("completed_today", False)
            name = attrs.get("name", "Daily Routine")
            
            if streak > 0 and not completed_today:
                nudge_msg = f"Don't break your streak! Complete your {name} routine today to keep your streak of {streak} active."
                payload = {
                    "channel": "push",
                    "recipient": "owner",
                    "title": "Streak Alert",
                    "body": nudge_msg,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                try:
                    graph.bus.publish("notification.enqueued", payload)
                except Exception:
                    pass
                triggered.append({
                    "routine_id": item["id"],
                    "name": name,
                    "streak": streak,
                    "message": nudge_msg
                })

    return triggered
