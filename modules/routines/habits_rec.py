"""Vital Habits Activity Recommender.

Recommends habits and actions matching stress levels and location context.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


def recommend_vital_habit(
    graph: Graph,
    lat: float,
    lon: float
) -> dict:
    """Recommends a healthy habit activity based on location and stress indicators."""
    session = graph.session(MODULE, SCOPES)
    
    # Check if we have high stress metrics recorded
    metrics = session.find_entities("metric", limit=10)
    high_stress = False
    
    for m in metrics:
        attrs = m.get("attrs", {})
        if attrs.get("type") == "stress_level" and attrs.get("value", 0) > 70:
            high_stress = True
            break

    if high_stress:
        return {
            "habit_title": "Box Breathing",
            "duration_minutes": 5,
            "reason": "Stress is elevated. We recommend taking 5 minutes to ground yourself here.",
            "coordinates": {"lat": lat, "lon": lon}
        }

    return {
        "habit_title": "Stretch & Hydrate",
        "duration_minutes": 10,
        "reason": "Keep consistent. Stretch and hydrate to keep energy balanced.",
        "coordinates": {"lat": lat, "lon": lon}
    }
