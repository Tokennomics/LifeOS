"""Habit Rings Aggregator.

Aggregates daily completion percentages across vital categories for ring visuals.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


def calculate_habit_rings(graph: Graph) -> dict:
    """Calculates rings completion values (0-100%) for core routine categories."""
    session = graph.session(MODULE, SCOPES)
    
    # We query tasks to see daily achievements
    tasks = session.find_entities("task", limit=200)
    
    cats = {"mindfulness": 0, "focus": 0, "physical": 0, "sleep": 0}
    totals = {"mindfulness": 2, "focus": 3, "physical": 1, "sleep": 1} # Goals

    for t in tasks:
        attrs = t.get("attrs", {})
        title = attrs.get("title", "").lower()
        status = attrs.get("status")
        
        if status == "completed" or attrs.get("completed_today") is True:
            # Map keyword cues to categories
            if any(k in title for k in ["breath", "meditate", "mindful", "relax"]):
                cats["mindfulness"] += 1
            elif any(k in title for k in ["focus", "study", "code", "work", "read"]):
                cats["focus"] += 1
            elif any(k in title for k in ["run", "gym", "climb", "lift", "walk", "stretch"]):
                cats["physical"] += 1
            elif any(k in title for k in ["sleep", "wind", "rest", "bed"]):
                cats["sleep"] += 1

    return {
        "rings": {
            "mindfulness": min(100.0, (cats["mindfulness"] / totals["mindfulness"]) * 100) if totals["mindfulness"] > 0 else 100.0,
            "focus": min(100.0, (cats["focus"] / totals["focus"]) * 100) if totals["focus"] > 0 else 100.0,
            "physical": min(100.0, (cats["physical"] / totals["physical"]) * 100) if totals["physical"] > 0 else 100.0,
            "sleep": min(100.0, (cats["sleep"] / totals["sleep"]) * 100) if totals["sleep"] > 0 else 100.0
        },
        "achievements_count": cats
    }
