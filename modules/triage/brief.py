"""Phase 2 Urgency/Triage OS — Daily Triage Briefing Module.

Reads the graph (tasks, goals, vitals energy baseline, reconnect decay) to generate
a structured daily "What Matters" briefing card for PWA surfaces and bot alerts.
"""

from datetime import datetime, timezone
from modules.horizon import gate
from modules.reconnect import decay
from modules.vitals import energy
from substrate.graph import Graph

SCOPES = {
    "tasks:read",
    "goals:read",
    "content:read",
    "metrics:read",
    "people:read",
}


def current_week_id() -> str:
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def generate_triage_brief(graph: Graph, cfg: dict | None = None) -> dict:
    """Compiles the daily triage briefing payload from graph state."""
    session = graph.session("triage", SCOPES)
    week = current_week_id()
    config = cfg or {}

    # 1. Fetch open tasks & focused goals
    all_tasks = session.find_entities("task")
    open_tasks = [t for t in all_tasks if t.get("attrs", {}).get("status", "open") == "open"]

    # Today/This week focus tasks
    week_tasks = [t for t in open_tasks if t.get("attrs", {}).get("week") == week]
    overdue_tasks = [t for t in open_tasks if t.get("attrs", {}).get("week", "") < week]

    all_goals = session.find_entities("goal")
    focused_goals = [g for g in all_goals if g.get("attrs", {}).get("focus") is True]

    # 2. Stuck work detection (>2 carryovers)
    stuck_tasks = [
        {
            "id": t["id"],
            "title": t.get("attrs", {}).get("title", ""),
            "carries": t.get("attrs", {}).get("carries", 0),
            "suggestion": "Break down into smallest 15-min next physical step.",
        }
        for t in open_tasks
        if t.get("attrs", {}).get("carries", 0) > 2
    ]

    # 3. Energy baseline shaping
    baseline = config.get("vitals", {}).get("energy_baseline", "normal")
    energy_windows = energy.windows(graph)
    if baseline == "tired":
        energy_advice = "Energy baseline is low: cap deep work to 3 items and schedule admin during daytime trough."
    else:
        energy_advice = "Normal energy: tackle deep work in evening focus windows."

    # 4. Reconnect nudges
    reconnect_nudges = decay.ranked(graph, limit=3)

    # 5. Gate status
    v01_gate = gate.gate_status(graph)

    # Construct priority inbox slot (single top item)
    top_escalation = None
    if overdue_tasks:
        top_escalation = {
            "type": "overdue_task",
            "title": overdue_tasks[0].get("attrs", {}).get("title", ""),
            "id": overdue_tasks[0]["id"],
        }
    elif week_tasks:
        top_escalation = {
            "type": "today_task",
            "title": week_tasks[0].get("attrs", {}).get("title", ""),
            "id": week_tasks[0]["id"],
        }

    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "top_escalation": top_escalation,
        "energy_baseline": baseline,
        "energy_advice": energy_advice,
        "energy_windows": energy_windows,
        "tasks_summary": {
            "this_week_open": len(week_tasks),
            "overdue_count": len(overdue_tasks),
            "total_open": len(open_tasks),
        },
        "focused_goals": [
            {"id": g["id"], "title": g.get("attrs", {}).get("title", "")}
            for g in focused_goals
        ],
        "stuck_work": stuck_tasks,
        "reconnect_nudges": reconnect_nudges[:3],
        "gate_status": v01_gate,
    }
