"""Automated Milestone Nudge & Goal Reminder Engine.

Scans active goals, checks milestone due dates, and dispatches proactive reminders
or notifications for upcoming and overdue milestones.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"goals:read", "goals:write", "admin:write"}
MODULE = "horizon"


def scan_milestone_nudges(graph: Graph) -> list[dict]:
    """Scans all active goals and generates nudge recommendations for due milestones."""
    session = graph.session(MODULE, SCOPES)
    goals = session.find_entities("goal", limit=500)
    
    now = datetime.now(timezone.utc)
    nudges = []

    for goal in goals:
        attrs = goal.get("attrs", {})
        milestones = attrs.get("milestones", [])
        if not milestones and "milestone" in attrs:
            # Fallback if single milestone represented
            milestones = [attrs["milestone"]]

        for index, m in enumerate(milestones):
            # Expect milestone dict format: {"title": str, "due_date": ISO_str, "status": str}
            if not isinstance(m, dict):
                continue
            
            title = m.get("title", f"Milestone #{index + 1}")
            status = m.get("status", "pending").lower().strip()
            due_str = m.get("due_date", "")

            if status in ("completed", "done", "x"):
                continue

            if not due_str:
                continue

            try:
                due_date = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                days_left = (due_date - now).days

                # Generate nudges for overdue or due-soon (<= 3 days) milestones
                if days_left < 0:
                    nudges.append({
                        "goal_id": goal["id"],
                        "goal_title": attrs.get("title") or attrs.get("name") or "Unnamed Goal",
                        "milestone_title": title,
                        "status": "overdue",
                        "days_difference": abs(days_left),
                        "message": f"Milestone '{title}' is overdue by {abs(days_left)} day(s)!"
                    })
                elif days_left <= 3:
                    nudges.append({
                        "goal_id": goal["id"],
                        "goal_title": attrs.get("title") or attrs.get("name") or "Unnamed Goal",
                        "milestone_title": title,
                        "status": "due_soon",
                        "days_difference": days_left,
                        "message": f"Milestone '{title}' is due in {days_left} day(s)."
                    })
            except Exception:
                # Ignore malformed ISO formats in dynamic schema
                continue

    # Auto-dispatch notification logs for all generated nudges
    for nudge in nudges:
        session.create_entity(
            "admin_item",
            {
                "type": "nudge_notification",
                "goal_id": nudge["goal_id"],
                "message": nudge["message"],
                "timestamp": now.isoformat()
            },
            source=MODULE
        )

    return nudges
