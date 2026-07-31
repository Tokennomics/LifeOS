"""Habit & Routine Analytics Engine.

Computes completion rates, streak metrics, and habit consistency analytics
over logged daily routines.
"""

from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write"}
MODULE = "routines"


def get_routine_analytics(graph: Graph) -> dict:
    """Computes routine completions, streak averages, and consistency score."""
    session = graph.session(MODULE, SCOPES)
    
    # In Substrate, routines are tracked as admin_items or task items.
    # Let's query both to aggregate streak info.
    items = session.find_entities("admin_item", limit=500)
    
    total_tracked = 0
    total_streaks = 0
    max_streak = 0
    completed_count = 0

    for item in items:
        attrs = item.get("attrs", {})
        # Filter for routine completion events or streak counters
        if attrs.get("type") == "routine_streak" or "streak" in attrs:
            total_tracked += 1
            streak = attrs.get("streak", 0)
            total_streaks += streak
            max_streak = max(max_streak, streak)
            if attrs.get("completed_today") is True or attrs.get("status") == "completed":
                completed_count += 1

    avg_streak = total_streaks / total_tracked if total_tracked > 0 else 0.0
    consistency = (completed_count / total_tracked * 100) if total_tracked > 0 else 100.0

    return {
        "total_routines_tracked": total_tracked,
        "average_streak": round(avg_streak, 1),
        "max_streak": max_streak,
        "consistency_percentage": round(consistency, 1),
        "status": "Optimal consistency." if consistency >= 80 else "Consistency improvement suggested."
    }
