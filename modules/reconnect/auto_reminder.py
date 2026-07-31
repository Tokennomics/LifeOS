"""Auto-Remind Inactive Connections.

Monitors connection decay scores and enqueues contact reminders.
"""

from datetime import datetime, timezone
from modules.reconnect import decay
from substrate.graph import Graph

SCOPES = {"people:read", "people:write", "events:read", "events:write"}
MODULE = "reconnect"


def enqueue_decay_reminders(graph: Graph) -> list[dict]:
    """Scans overdue social connections and enqueues reminder notifications."""
    overdue_people = decay.ranked(graph, limit=100)
    enqueued = []

    for person in overdue_people:
        if person["overdue"] >= 1.0:
            reminder_msg = f"It has been {person['days_since']} days since you contacted {person['name']}. Reach out soon!"
            payload = {
                "channel": "push",
                "recipient": "owner",
                "title": "Reconnect Reminder",
                "body": reminder_msg,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            try:
                graph.bus.publish("notification.enqueued", payload)
            except Exception:
                pass
            enqueued.append({
                "person_id": person["id"],
                "name": person["name"],
                "message": reminder_msg
            })

    return enqueued
