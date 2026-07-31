"""Mindfulness & Screen-Time Tracker.

Logs focus sessions and tracks distraction rates to compute digital wellness metrics.
"""

from substrate.graph import Graph

SCOPES = {"content:read", "content:write"}
MODULE = "routines"


def log_focus_session(
    graph: Graph,
    duration_minutes: int,
    distraction_count: int,
    note: str = ""
) -> dict:
    """Logs a mindfulness focus session as a content entity in the graph."""
    if duration_minutes <= 0:
        raise ValueError("duration must be greater than zero")

    session = graph.session(MODULE, SCOPES)
    
    attrs = {
        "type": "focus_session",
        "duration_minutes": duration_minutes,
        "distraction_count": distraction_count,
        "note": note
    }
    
    entity_id = session.create_entity("content", attrs, source="mindfulness_tracker")
    return {
        "session_id": entity_id,
        "duration_minutes": duration_minutes,
        "distraction_count": distraction_count,
        "note": note,
        "wellness_score": round(duration_minutes / (distraction_count + 1), 1)
    }


def get_mindfulness_summary(graph: Graph) -> dict:
    """Computes averages and summary statistics for logged focus sessions."""
    session = graph.session(MODULE, SCOPES)
    
    entities = session.find_entities("content", limit=500)
    
    total_sessions = 0
    total_duration = 0
    total_distractions = 0

    for ent in entities:
        attrs = ent.get("attrs", {})
        if attrs.get("type") == "focus_session":
            total_sessions += 1
            total_duration += attrs.get("duration_minutes", 0)
            total_distractions += attrs.get("distraction_count", 0)

    if total_sessions == 0:
        return {
            "total_sessions": 0,
            "average_duration_minutes": 0.0,
            "average_distractions": 0.0,
            "overall_wellness_score": 100.0,
            "status": "No focus sessions logged yet."
        }

    avg_duration = total_duration / total_sessions
    avg_distractions = total_distractions / total_sessions
    overall_score = avg_duration / (avg_distractions + 1)

    return {
        "total_sessions": total_sessions,
        "average_duration_minutes": round(avg_duration, 1),
        "average_distractions": round(avg_distractions, 1),
        "overall_wellness_score": round(overall_score * 10, 1),
        "status": "Excellent focus clarity." if overall_score >= 15 else "Focus improvement recommended."
    }
