"""Crew Joint Goals Tracker.

Tracks shared goals and milestones assigned to entire crews.
"""

from substrate.graph import Graph

SCOPES = {"goals:read", "goals:write", "*"}
MODULE = "horizon"


def create_crew_goal(
    graph: Graph,
    crew_id: str,
    title: str,
    target_date: str
) -> dict:
    """Creates a shared goal for a crew and links it via a feeds edge."""
    if not crew_id.strip() or not title.strip():
        raise ValueError("crew_id and title are required")

    session = graph.session(MODULE, SCOPES)
    
    attrs = {
        "title": title,
        "target_date": target_date,
        "crew_id": crew_id,
        "type": "crew_goal",
        "status": "active"
    }
    
    goal_id = session.create_entity("goal", attrs, source="crew_goals")
    
    # Link crew to goal
    try:
        session.create_edge(crew_id, goal_id, "feeds", source="crew_goals")
    except Exception:
        pass

    return {
        "goal_id": goal_id,
        "crew_id": crew_id,
        "title": title,
        "target_date": target_date,
        "status": "active"
    }
