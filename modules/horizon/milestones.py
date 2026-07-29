"""Goal Milestones & Sub-goal Breakdown.

Decomposes 12-week goals into concrete milestone deliverables and calculates
live completion progress ratios.
"""

from substrate.graph import Graph

SCOPES = {"goals:read", "goals:write", "tasks:read", "tasks:write", "content:read", "content:write"}


def add_milestone(graph: Graph, goal_id: str, title: str, target_week: str | None = None, source: str = "milestones") -> dict:
    session = graph.session("horizon", SCOPES)
    goal = session.get_entity(goal_id)
    if goal is None or goal["kind"] != "goal":
        raise ValueError(f"Goal entity not found: {goal_id}")

    ms_id = session.create_entity(
        "content",
        {
            "type": "milestone",
            "goal_id": goal_id,
            "title": title.strip(),
            "target_week": target_week or "",
            "status": "open",
        },
        source=source,
    )
    session.create_edge(ms_id, goal_id, "feeds", source=source)
    return {"id": ms_id, "goal_id": goal_id, "title": title, "target_week": target_week or "", "status": "open"}


def complete_milestone(graph: Graph, milestone_id: str, source: str = "milestones") -> dict:
    session = graph.session("horizon", SCOPES)
    ms = session.get_entity(milestone_id)
    if ms is None or ms["kind"] != "content" or ms["attrs"].get("type") != "milestone":
        raise ValueError(f"Milestone entity not found: {milestone_id}")

    session.update_entity(milestone_id, {"status": "completed"}, source=source)
    return {"id": milestone_id, "status": "completed"}


def goal_progress(graph: Graph, goal_id: str) -> dict:
    session = graph.session("horizon", SCOPES)
    goal = session.get_entity(goal_id)
    if goal is None or goal["kind"] != "goal":
        raise ValueError(f"Goal entity not found: {goal_id}")

    # Fetch milestones
    all_content = session.find_entities("content", {"type": "milestone"}, limit=200)
    ms_list = [m for m in all_content if m.get("attrs", {}).get("goal_id") == goal_id]
    completed_ms = [m for m in ms_list if m.get("attrs", {}).get("status") == "completed"]

    # Fetch tasks linked to goal
    all_tasks = session.find_entities("task", limit=500)
    goal_tasks = [t for t in all_tasks if t.get("attrs", {}).get("goal_id") == goal_id or t.get("attrs", {}).get("goal") == goal_id]
    completed_tasks = [t for t in goal_tasks if t.get("attrs", {}).get("status") in ("done", "completed")]

    ms_ratio = len(completed_ms) / len(ms_list) if ms_list else 0.0
    task_ratio = len(completed_tasks) / len(goal_tasks) if goal_tasks else 0.0

    # Overall progress score: weighted average of milestones (60%) and tasks (40%)
    if ms_list and goal_tasks:
        progress_pct = round((ms_ratio * 0.6 + task_ratio * 0.4) * 100, 1)
    elif ms_list:
        progress_pct = round(ms_ratio * 100, 1)
    elif goal_tasks:
        progress_pct = round(task_ratio * 100, 1)
    else:
        progress_pct = 0.0

    return {
        "goal_id": goal_id,
        "goal_title": goal.get("attrs", {}).get("title", ""),
        "progress_percent": progress_pct,
        "milestones": {
            "total": len(ms_list),
            "completed": len(completed_ms),
            "ratio": round(ms_ratio, 2),
            "items": [
                {
                    "id": m["id"],
                    "title": m.get("attrs", {}).get("title", ""),
                    "status": m.get("attrs", {}).get("status", "open"),
                    "target_week": m.get("attrs", {}).get("target_week", ""),
                }
                for m in ms_list
            ],
        },
        "tasks": {
            "total": len(goal_tasks),
            "completed": len(completed_tasks),
            "ratio": round(task_ratio, 2),
        },
    }
