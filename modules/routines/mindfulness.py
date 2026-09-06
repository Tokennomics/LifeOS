"""Personalized Mindfulness Routine Generator.

Recommends breathing/meditation duration targets based on stress logs.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


MAX_MINUTES = 24 * 60


def log_focus_session(graph: Graph, duration_minutes: int, distraction_count: int,
                      note: str = "", source: str = MODULE) -> dict:
    """Record one focus session.

    `POST /v1/routines/mindfulness/session` has called this since the endpoint was written
    and the function has never existed, so every attempt to log a session was a 500. Found
    by exercising all 275 body-taking endpoints with valid bodies rather than empty ones —
    the empty-body sweep only reached the 422 and stopped there.

    Stored as a `metric`, which is what the v0 schema already has for "a number about you
    over time"; the session detail lives in `attrs` per the extend-via-attrs rule.
    """
    try:
        minutes = int(duration_minutes)
        distractions = int(distraction_count)
    except (TypeError, ValueError):
        raise ValueError("duration_minutes and distraction_count must be whole numbers")
    if minutes <= 0 or minutes > MAX_MINUTES:
        raise ValueError(f"duration_minutes must be between 1 and {MAX_MINUTES}")
    if distractions < 0:
        raise ValueError("distraction_count cannot be negative")

    session = graph.session(MODULE, SCOPES)
    metric_id = session.create_entity("metric", {
        "type": "focus_session",
        "value": minutes,
        "distraction_count": distractions,
        # Distractions per hour is the comparable number — a 15-minute sit with two
        # interruptions is a worse session than a 90-minute one with three, and the raw
        # count says the opposite.
        "distractions_per_hour": round(distractions / (minutes / 60), 1),
        "note": str(note or "")[:500],
    }, source=source)

    return {"logged": True, "session_id": metric_id, "duration_minutes": minutes,
            "distraction_count": distractions, **focus_history(graph)}


def focus_history(graph: Graph, limit: int = 50) -> dict:
    """Totals across recorded sessions — what makes logging one worth doing."""
    session = graph.session(MODULE, SCOPES)
    rows = [row for row in session.find_entities("metric", limit=limit)
            if row.get("attrs", {}).get("type") == "focus_session"]
    if not rows:
        return {"sessions": 0, "total_minutes": 0, "average_distractions_per_hour": 0.0}

    minutes = sum(int(row["attrs"].get("value") or 0) for row in rows)
    rates = [float(row["attrs"].get("distractions_per_hour") or 0) for row in rows]
    return {
        "sessions": len(rows),
        "total_minutes": minutes,
        "average_distractions_per_hour": round(sum(rates) / len(rates), 1),
    }


def generate_mindfulness_target(graph: Graph) -> dict:
    """Recommends breathing and focus minutes based on stress metric logs."""
    session = graph.session(MODULE, SCOPES)
    
    metrics = session.find_entities("metric", limit=20)
    stress_logs = [m for m in metrics if m.get("attrs", {}).get("type") == "stress_index"]

    if not stress_logs:
        return {
            "recommended_duration_minutes": 5,
            "session_type": "standard_wind_down",
            "message": "No recent stress logs found. Recommending a baseline 5-minute session."
        }

    # Find maximum recent stress index
    max_stress = 0
    for s in stress_logs:
        val = s.get("attrs", {}).get("value", 50)
        max_stress = max(max_stress, val)

    if max_stress >= 70:
        return {
            "recommended_duration_minutes": 15,
            "session_type": "stress_relief_breathwork",
            "message": f"Elevated stress level of {max_stress} detected. Recommending a deep 15-minute breathwork session."
        }

    return {
        "recommended_duration_minutes": 10,
        "session_type": "focus_meditation",
        "message": f"Moderate stress level of {max_stress} detected. Recommending a 10-minute focus meditation."
    }
