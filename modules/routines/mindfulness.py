"""Personalized Mindfulness Routine Generator.

Recommends breathing/meditation duration targets based on stress logs.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


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
