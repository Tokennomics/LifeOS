"""Goal Forecaster & Automated Weekly Retrospective.

Computes 12-week goal completion probability forecasts and generates automated
weekly retrospectives based on velocity and routine consistency.
"""

from modules.horizon import analytics, milestones
from modules.routines import tracker
from substrate.graph import Graph

SCOPES = {"goals:read", "tasks:read", "content:read"}
MODULE = "horizon"


def forecast_goal_completion(graph: Graph, goal_id: str) -> dict:
    """Forecasts completion probability and estimated weeks for a goal."""
    if not goal_id.strip():
        raise ValueError("goal_id required")

    progress_info = milestones.goal_progress(graph, goal_id)
    overall_progress = progress_info.get("overall_progress", 0.0)

    velocity_info = analytics.goal_velocity(graph)
    weekly_velocity = velocity_info.get("average_weekly_velocity", 1.0)

    # Estimate remaining weeks
    remaining_ratio = 1.0 - (overall_progress / 100.0)
    estimated_weeks = round(max(remaining_ratio * 4.0 / max(weekly_velocity, 0.5), 1.0), 1)

    prob = min(round(overall_progress * 0.6 + weekly_velocity * 15.0), 99)

    return {
        "goal_id": goal_id,
        "title": progress_info.get("title", ""),
        "progress_percentage": overall_progress,
        "weekly_velocity": weekly_velocity,
        "completion_probability": prob,
        "estimated_weeks_remaining": estimated_weeks,
        "on_track": prob >= 50,
    }


def generate_auto_retro(graph: Graph, source: str = MODULE) -> dict:
    """Generates an automated weekly retrospective summary."""
    session = graph.session(MODULE, SCOPES)

    tasks = session.find_entities("task", limit=200)
    done_tasks = [t for t in tasks if t.get("attrs", {}).get("status") == "done"]

    routines = tracker.get_routines_status(graph)
    active_streaks = [r for r in routines if r.get("streak", 0) > 0]

    headline = f"Weekly Retro: Finished {len(done_tasks)} tasks across {len(active_streaks)} active routine streaks."
    
    return {
        "headline": headline,
        "done_tasks_count": len(done_tasks),
        "active_streaks_count": len(active_streaks),
        "routines": routines,
    }
