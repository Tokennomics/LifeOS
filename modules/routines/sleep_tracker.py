"""Circadian Rhythm & Sleep Alignment Tracker.

Logs sleep metrics, analyses sleep consistency, and computes a circadian rhythm
alignment score based on wake times and rest durations.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write"}
MODULE = "routines"


def log_sleep_data(graph: Graph, date_str: str, hours_slept: float,
                   sleep_quality: int, wake_time_str: str, source: str = MODULE) -> dict:
    """Logs a sleep record to the graph database."""
    if hours_slept <= 0 or hours_slept > 24:
        raise ValueError("hours_slept must be between 0 and 24")
    if not (1 <= sleep_quality <= 10):
        raise ValueError("sleep_quality must be between 1 and 10")

    session = graph.session(MODULE, SCOPES)
    record_id = session.create_entity(
        "admin_item",
        {
            "type": "sleep_record",
            "date": date_str.strip(),
            "hours_slept": hours_slept,
            "sleep_quality": sleep_quality,
            "wake_time": wake_time_str.strip(),
            "logged_at": datetime.now(timezone.utc).isoformat()
        },
        source=source
    )
    return {"record_id": record_id, "status": "logged"}


def get_circadian_summary(graph: Graph) -> dict:
    """Retrieves sleep history and computes circadian alignment metrics."""
    session = graph.session(MODULE, SCOPES)
    records = session.find_entities("admin_item", {"type": "sleep_record"}, limit=30)

    if not records:
        return {
            "average_hours": 0.0,
            "average_quality": 0.0,
            "circadian_alignment_score": 100,  # Default neutral score
            "status": "No sleep records logged yet."
        }

    total_hours = 0.0
    total_quality = 0.0
    wake_hours = []

    for r in records:
        attrs = r.get("attrs", {})
        total_hours += attrs.get("hours_slept", 8.0)
        total_quality += attrs.get("sleep_quality", 7)
        
        # Parse wake time (e.g., "07:30") to compute variance
        wake_str = attrs.get("wake_time", "")
        if ":" in wake_str:
            try:
                parts = wake_str.split(":")
                hh = int(parts[0])
                mm = int(parts[1])
                wake_hours.append(hh + mm / 60.0)
            except Exception:
                pass

    avg_hours = total_hours / len(records)
    avg_quality = total_quality / len(records)

    # Compute wake time standard deviation for circadian rhythm consistency score
    alignment_score = 100
    if len(wake_hours) > 1:
        mean_wake = sum(wake_hours) / len(wake_hours)
        variance = sum((x - mean_wake) ** 2 for x in wake_hours) / len(wake_hours)
        std_dev = variance ** 0.5
        # Standard deviation of 0 hours variance = 100 score. Deduct 15 points per hour of deviation.
        alignment_score = max(10, int(100 - (std_dev * 15)))

    status_msg = "Consistent sleep routine." if alignment_score >= 80 else "Circadian rhythm is erratic. Try keeping wake times consistent."

    return {
        "average_hours": round(avg_hours, 1),
        "average_quality": round(avg_quality, 1),
        "circadian_alignment_score": alignment_score,
        "status": status_msg
    }
