"""Horizon — weekly planner: goals + open tasks (+ calendar busy blocks) -> this week's if-then task list.

The plan IS the graph: selected tasks get attrs.week = "YYYY-Www". No separate plan object.
/log N marks the Nth task of the current week done.

CLI:  python -m modules.horizon.planner [--offline] [--config path]
"""

import argparse
import datetime
import json

from substrate.graph import Graph

SCOPES = {"goals:read", "tasks:read", "tasks:write", "events:read"}

PLANNER_SYSTEM = (
    "You are Horizon's weekly planner in a personal Life OS. Input: the user's vision(s), "
    "goals, open tasks, and calendar busy blocks for the week. Output: 3-7 tasks for this "
    "week that move the goals. Reuse open tasks where they fit (set existing_task_id); "
    "otherwise create new concrete ones. Every task gets an if-then implementation intention "
    "anchored to a specific day/time or situation, scheduled around the busy blocks. "
    "Progress monitoring beats ambition: prefer few tasks that will actually happen."
)

PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "if_then": {"type": "string"},
                    "existing_task_id": {"type": "string"},
                    "goal_title": {"type": "string"},
                },
                "required": ["title", "if_then", "existing_task_id", "goal_title"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tasks"],
    "additionalProperties": False,
}

_FALLBACK_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def week_id(dt: datetime.datetime | datetime.date | None = None) -> str:
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def plan_week(graph: Graph, claude=None, week: str | None = None, source: str = "planner") -> dict:
    session = graph.session("horizon", SCOPES)
    week = week or week_id()

    existing = session.find_entities("task", {"week": week}, limit=50)
    if len(existing) >= 3:  # idempotent Monday re-runs
        return {"week": week, "tasks": len(existing), "method": "already-planned"}

    goals = session.find_entities("goal", {"level": "goal"}, limit=50)
    open_tasks = [t for t in session.find_entities("task", {"status": "open"}, limit=200)
                  if t["attrs"].get("week") != week]

    from modules.vitals import energy  # Vitals is a layer: schedulers consume its windows

    if claude is not None and claude.available:
        method = "claude"
        busy = _busy_this_week(session, week)
        context = json.dumps({
            "week": week,
            "visions": [v["attrs"].get("title") for v in session.find_entities("goal", {"level": "vision"})],
            "goals": [{"id": g["id"], "title": g["attrs"].get("title"), "why": g["attrs"].get("why", "")} for g in goals],
            "open_tasks": [{"id": t["id"], "title": t["attrs"].get("title")} for t in open_tasks],
            "busy_blocks": busy,
            "energy_windows": energy.windows(graph),
        })
        data = claude.complete_json(PLANNER_SYSTEM, context, schema=PLANNER_SCHEMA)
        proposals = data["tasks"][:7]
    else:
        method = "offline"
        peak = energy.phase_start(graph, "peak", "17:00")
        proposals = [
            {"title": t["attrs"].get("title", ""), "if_then": t["attrs"].get("if_then", ""),
             "existing_task_id": t["id"], "goal_title": ""}
            for t in open_tasks[:7]
        ]
        slot = 0
        for goal in goals:
            if len(proposals) >= 3:
                break
            title = goal["attrs"].get("title", "goal")
            proposals.append({
                "title": f"Advance: {title}",
                "if_then": f"If it's {_FALLBACK_DAYS[slot % len(_FALLBACK_DAYS)]} {peak}, "
                           f"then I spend 45 min on '{title}'",
                "existing_task_id": "", "goal_title": title,
            })
            slot += 1

    open_by_id = {t["id"]: t for t in open_tasks}
    goal_by_title = {g["attrs"].get("title"): g["id"] for g in goals}
    count = 0
    for p in proposals:
        if p["existing_task_id"] in open_by_id:
            patch = {"week": week}
            if p["if_then"]:
                patch["if_then"] = p["if_then"]
            session.update_entity(p["existing_task_id"], patch, source=source)
        else:
            tid = session.create_entity(
                "task", {"title": p["title"], "if_then": p["if_then"], "status": "open", "week": week},
                source=source,
            )
            goal_id = goal_by_title.get(p["goal_title"])
            if goal_id:
                session.create_edge(tid, goal_id, "feeds", source=source)
        count += 1

    graph.bus.publish("plan.updated", {"week": week, "tasks": count, "module": "horizon"})
    return {"week": week, "tasks": count, "method": method}


def _busy_this_week(session, week: str) -> list[dict]:
    busy = []
    for ev in session.find_entities("event", {"busy": True}, limit=200):
        start = ev["attrs"].get("start", "")
        try:
            dt = datetime.datetime.fromisoformat(start)
        except ValueError:
            continue
        if week_id(dt) == week:
            busy.append({"start": start, "end": ev["attrs"].get("end", "")})
    return sorted(busy, key=lambda b: b["start"])


def week_tasks(graph: Graph, week: str | None = None) -> list[dict]:
    session = graph.session("horizon", SCOPES)
    return session.find_entities("task", {"week": week or week_id()}, limit=50)


def format_week(graph: Graph, week: str | None = None) -> str:
    week = week or week_id()
    tasks = week_tasks(graph, week)
    if not tasks:
        return f"No plan for {week} yet — send /plan."
    lines = [f"Plan for {week}:"]
    for i, task in enumerate(tasks, 1):
        mark = "x" if task["attrs"].get("status") == "done" else " "
        line = f"{i}. [{mark}] {task['attrs'].get('title', '')}"
        if task["attrs"].get("if_then"):
            line += f"\n   ({task['attrs']['if_then']})"
        lines.append(line)
    lines.append("Log with /log <number>.")
    return "\n".join(lines)


def log_done(graph: Graph, n: int, week: str | None = None, source: str = "log") -> str:
    week = week or week_id()
    tasks = week_tasks(graph, week)
    if not 1 <= n <= len(tasks):
        raise ValueError(f"no task #{n} in {week} (have {len(tasks)})")
    task = tasks[n - 1]
    session = graph.session("horizon", SCOPES)
    session.update_entity(
        task["id"], {"status": "done", "done_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
        source=source,
    )
    return task["attrs"].get("title", "")


def main():
    from gateway.claude import ClaudeGateway
    from substrate import load_config
    from substrate.migrate import migrate

    parser = argparse.ArgumentParser(description="Horizon weekly planner")
    parser.add_argument("--config", default=None)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.config)
    graph = Graph(migrate(cfg), default_owner=cfg.get("owner", {}).get("id"))
    claude = None if args.offline else ClaudeGateway(cfg)
    result = plan_week(graph, claude=claude)
    print(json.dumps(result))
    print(format_week(graph, result["week"]))


if __name__ == "__main__":
    main()
