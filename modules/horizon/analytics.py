"""Goal Velocity & Trends Analytics.

Calculates task completion velocity and weekly momentum per goal across ISO weeks.
"""

from collections import defaultdict
from substrate.graph import Graph

SCOPES = {"goals:read", "tasks:read", "metrics:read"}


def goal_velocity(graph: Graph) -> dict:
    """Computes task completion velocity and weekly trends for active goals."""
    session = graph.session("horizon", SCOPES)
    goals = session.find_entities("goal")
    tasks = session.find_entities("task", limit=500)

    # Group completed tasks by goal_id and week
    weekly_counts = defaultdict(lambda: defaultdict(int))
    total_completed = defaultdict(int)
    total_planned = defaultdict(int)

    for t in tasks:
        attrs = t.get("attrs", {})
        gid = attrs.get("goal_id") or attrs.get("goal")
        if not gid:
            continue
        week = attrs.get("week")
        status = attrs.get("status")

        total_planned[gid] += 1
        if status in ("done", "completed"):
            total_completed[gid] += 1
            if week:
                weekly_counts[gid][week] += 1

    out = []
    for g in goals:
        gid = g["id"]
        title = g.get("attrs", {}).get("title", "")
        level = g.get("attrs", {}).get("level", "goal")
        is_focused = g.get("attrs", {}).get("focus", False)

        counts_by_week = dict(weekly_counts[gid])
        active_weeks = len(counts_by_week)
        total_done = total_completed[gid]
        total_p = total_planned[gid]

        velocity = round(total_done / active_weeks, 2) if active_weeks > 0 else 0.0
        remaining_tasks = total_p - total_done

        out.append({
            "goal_id": gid,
            "title": title,
            "level": level,
            "focus": is_focused,
            "total_planned": total_p,
            "total_completed": total_done,
            "remaining_tasks": remaining_tasks,
            "weekly_velocity": velocity,
            "weekly_counts": counts_by_week,
        })

    return {
        "total_goals": len(goals),
        "goals": out,
    }
