"""Growth Loop — Post-Meet Event Feedback & Crew Activation.

Tracks post-meet event attendance, rating feedback, and measures the core
growth metric (crews that have met ≥2 times).
"""

from substrate.graph import Graph

SCOPES = {"metrics:read", "metrics:write", "content:read"}


def record_event_feedback(graph: Graph, crew_id: str, event_id: str, rating: int,
                          notes: str = "", source: str = "growth") -> dict:
    """Records post-meet feedback for a crew event."""
    if not 1 <= rating <= 5:
        raise ValueError("rating must be an integer between 1 and 5")
    if not crew_id.strip():
        raise ValueError("crew_id required")

    session = graph.session("growth", SCOPES)
    metric_id = session.create_entity(
        "metric",
        {
            "type": "event_feedback",
            "crew_id": crew_id.strip(),
            "event_id": event_id.strip(),
            "rating": rating,
            "notes": notes.strip(),
        },
        source=source,
    )
    graph.bus.publish("event.attended", {"crew_id": crew_id, "event_id": event_id, "rating": rating, "module": "growth"})
    return {"metric_id": metric_id, "crew_id": crew_id, "event_id": event_id, "rating": rating}


def crew_activation_status(graph: Graph, crew_id: str) -> dict:
    """Calculates crew meeting count and activation tier."""
    session = graph.session("growth", SCOPES)
    all_feedback = session.find_entities("metric", {"type": "event_feedback"}, limit=500)

    crew_items = [f for f in all_feedback if f.get("attrs", {}).get("crew_id") == crew_id]
    meet_count = len(crew_items)
    is_activated = meet_count >= 2

    ratings = [f.get("attrs", {}).get("rating", 5) for f in crew_items]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0

    return {
        "crew_id": crew_id,
        "meet_count": meet_count,
        "is_activated": is_activated,
        "average_rating": avg_rating,
        "status": "activated" if is_activated else "onboarding",
    }
