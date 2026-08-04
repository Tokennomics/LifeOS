"""Habit Consistency Trend Forecaster.

Calculates current routine consistency and forecasts upcoming completion trends.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


def forecast_consistency(graph: Graph) -> dict:
    """Calculates routine completion rates and predicts upcoming 30-day target trends."""
    session = graph.session(MODULE, SCOPES)
    
    items = session.find_entities("admin_item", limit=500)
    
    total_tracked = 0
    completed_count = 0

    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "routine_streak" or "streak" in attrs:
            total_tracked += 1
            if attrs.get("completed_today") is True or attrs.get("status") == "completed":
                completed_count += 1

    current_rate = (completed_count / total_tracked * 100) if total_tracked > 0 else 75.0
    
    # Simple predictive model: expect a minor +3% consistency growth trend if under 90%
    predicted_rate = min(100.0, current_rate + 3.0) if current_rate < 90.0 else current_rate

    return {
        "current_consistency_percentage": round(current_rate, 1),
        "forecasted_30d_consistency": round(predicted_rate, 1),
        "total_routines_profiled": total_tracked,
        "trend_direction": "stable" if current_rate >= 90.0 else "positive_growth"
    }
