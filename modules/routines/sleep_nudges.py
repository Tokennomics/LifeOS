"""Circadian Rhythm & Sleep Nudge Engine.

Detects sleep deprivation patterns and issues proactive evening notifications.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


def generate_circadian_nudge(graph: Graph) -> dict | None:
    """Analyzes sleep logs to push custom evening wind-down notifications."""
    session = graph.session(MODULE, SCOPES)
    
    metrics = session.find_entities("metric", limit=20)
    sleep_records = [m for m in metrics if m.get("attrs", {}).get("type") == "sleep_record"]

    if not sleep_records:
        return None

    # Calculate average hours slept
    total_hours = 0.0
    for r in sleep_records:
        total_hours += r.get("attrs", {}).get("hours_slept", 8.0)
    avg_hours = total_hours / len(sleep_records)

    if avg_hours < 7.0:
        nudge_msg = f"Your average sleep duration is {round(avg_hours, 1)} hours. We suggest starting your wind-down routine 1 hour earlier tonight."
        payload = {
            "channel": "push",
            "recipient": "owner",
            "title": "Circadian Nudge",
            "body": nudge_msg,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        try:
            graph.bus.publish("notification.enqueued", payload)
        except Exception:
            pass
        return {
            "nudge_triggered": True,
            "average_sleep": round(avg_hours, 1),
            "message": nudge_msg
        }

    return {
        "nudge_triggered": False,
        "average_sleep": round(avg_hours, 1),
        "message": "Sleep patterns look healthy."
    }
