"""Energy & Focus Balance Analytics.

Evaluates task intensity vs energy baselines to prevent burnout, outputting
cognitive load metrics and proactive recovery recommendations.
"""

from substrate.graph import Graph

SCOPES = {"tasks:read", "goals:read", "metrics:read"}
MODULE = "horizon"


def get_energy_balance(graph: Graph) -> dict:
    """Calculates cognitive load, burnout risk, and recovery recommendations."""
    session = graph.session(MODULE, SCOPES)

    # Fetch open tasks
    tasks = session.find_entities("task", limit=200)
    open_tasks = [t for t in tasks if t.get("attrs", {}).get("status") in ("open", "in_progress")]

    # Fetch active goals
    goals = session.find_entities("goal", limit=50)
    active_goals = [g for g in goals if g.get("attrs", {}).get("focus") is True]

    # Fetch latest energy level
    metrics = session.find_entities("metric", {"type": "energy"}, limit=10)
    energy_level = 5.0
    if metrics:
        energy_level = float(metrics[0].get("attrs", {}).get("level", 5.0))

    # Calculate cognitive load index
    task_count = len(open_tasks)
    goal_count = len(active_goals)
    load_index = round((task_count * 0.5 + goal_count * 1.5) / (max(energy_level, 1.0) / 2.0), 2)

    if load_index > 8.0:
        risk = "high"
        rec = "Burnout risk high: Schedule a 30-minute recovery walk and park 2 low-priority tasks."
    elif load_index > 4.0:
        risk = "moderate"
        rec = "Balanced load: Maintain current focus slots with 10-minute micro-breaks between tasks."
    else:
        risk = "low"
        rec = "High capacity available: Great time to take on a high-leverage focus task!"

    return {
        "open_tasks_count": task_count,
        "active_goals_count": goal_count,
        "energy_level": energy_level,
        "cognitive_load_index": load_index,
        "burnout_risk": risk,
        "recommendation": rec,
    }
