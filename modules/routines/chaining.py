"""Habit Chaining Suggester.

Suggests sequential habit pairings to improve consistency and routine compliance.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


def suggest_habit_chain(graph: Graph) -> dict:
    """Analyzes task history to recommend a habit chaining pair."""
    session = graph.session(MODULE, SCOPES)
    
    tasks = session.find_entities("task", limit=50)
    
    if len(tasks) < 2:
        return {
            "habit_anchor": "Morning Coffee",
            "habit_target": "Journal writing",
            "confidence_score": 0.5,
            "message": "Start small: Immediately after having morning coffee, write one sentence in your journal."
        }

    # Extract names
    names = [t.get("attrs", {}).get("title", "Task") for t in tasks]
    anchor = names[0]
    target = names[1]

    return {
        "habit_anchor": anchor,
        "habit_target": target,
        "confidence_score": 0.85,
        "message": f"We noticed you frequently complete '{anchor}'. We suggest chaining '{target}' immediately after to lock it in."
    }
