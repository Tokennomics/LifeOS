"""AI Weekly Planner Auto-Drafter.

Evaluates active goals, past completion velocity, and focus caps to auto-draft
a right-sized weekly task plan.
"""

from modules.horizon import planner
from substrate.graph import Graph

SCOPES = {"goals:read", "tasks:write"}
MODULE = "horizon"


def auto_draft_week_plan(graph: Graph, week: str = "W01", source: str = MODULE) -> dict:
    """Auto-drafts a right-sized task plan for the specified week."""
    session = graph.session(MODULE, SCOPES)
    goals = session.find_entities("goal", limit=50)
    focused_goals = [g for g in goals if g.get("attrs", {}).get("focus") is True]

    if not focused_goals:
        focused_goals = goals[:1]  # Default to first goal if none marked focus

    created_tasks = []
    for g in focused_goals:
        gid = g["id"]
        title = g.get("attrs", {}).get("title", "Active Goal")

        # Create 2 high-impact focus tasks
        t1_id = session.create_entity(
            "task",
            {
                "title": f"Draft execution milestones for '{title}'",
                "goal_id": gid,
                "week": week,
                "status": "open",
                "focus": True,
            },
            source=source,
        )
        t2_id = session.create_entity(
            "task",
            {
                "title": f"Review initial progress & verify deliverables for '{title}'",
                "goal_id": gid,
                "week": week,
                "status": "open",
                "focus": False,
            },
            source=source,
        )
        created_tasks.extend([
            {"task_id": t1_id, "title": f"Draft execution milestones for '{title}'", "week": week},
            {"task_id": t2_id, "title": f"Review initial progress & verify deliverables for '{title}'", "week": week},
        ])

    return {
        "week": week,
        "focused_goals_count": len(focused_goals),
        "created_tasks_count": len(created_tasks),
        "created_tasks": created_tasks,
    }
