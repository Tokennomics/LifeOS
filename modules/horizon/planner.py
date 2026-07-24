"""Horizon — weekly planner: goals + open tasks (+ calendar busy blocks) -> this week's if-then task list.

The plan IS the graph: selected tasks get attrs.week = "YYYY-Www". No separate plan object.
/log N marks the Nth task of the current week done.

CLI:  python -m modules.horizon.planner [--offline] [--config path]
"""

import argparse
import datetime
import json

from modules.horizon import core
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

def week_id(dt: datetime.datetime | datetime.date | None = None) -> str:
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def plan_week(graph: Graph, claude=None, week: str | None = None, source: str = "planner",
              energy_baseline: str = "tired") -> dict:
    """Plan the week. The offline path runs the shared anti-hindrance core (T3):
    finishes stuck work before starting new, shapes deep work into the evening and
    admin into the trough, and hard-caps the week while the baseline is tired."""
    session = graph.session("horizon", SCOPES)
    week = week or week_id()
    cap = core.weekly_cap(energy_baseline)

    existing = session.find_entities("task", {"week": week}, limit=50)
    if len(existing) >= cap:  # idempotent re-runs
        return {"week": week, "tasks": len(existing), "method": "already-planned"}

    goals = session.find_entities("goal", {"level": "goal"}, limit=50)
    open_tasks = [t for t in session.find_entities("task", {"status": "open"}, limit=200)
                  if t["attrs"].get("week") != week]
    open_by_id = {t["id"]: t for t in open_tasks}
    goal_by_title = {g["attrs"].get("title"): g["id"] for g in goals}

    if claude is not None and claude.available:
        method = "claude"
        from modules.vitals import energy  # Vitals is a layer: schedulers consume its windows
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
        descriptors = []
        for p in data["tasks"][:cap]:
            eid = p.get("existing_task_id") or None
            if eid in open_by_id:
                cycles = int(open_by_id[eid]["attrs"].get("cycles", 0) or 0) + 1
            else:
                eid, cycles = None, 1
            descriptors.append({
                "origin": "reuse" if eid else "new", "id": eid,
                "title": p["title"], "if_then": p["if_then"], "status": "open",
                "cycles": cycles, "smallest_piece": cycles > core.STALE_CYCLES,
                "goal_title": p.get("goal_title", ""),
            })
    else:
        method = "offline"
        descriptors = core.offline_plan({
            "baseline": energy_baseline,
            "goals": [{"title": g["attrs"].get("title", ""), "focus": g["attrs"].get("focus", False)}
                      for g in goals],
            "open_tasks": [{"id": t["id"], "title": t["attrs"].get("title", ""),
                            "if_then": t["attrs"].get("if_then", ""),
                            "cycles": t["attrs"].get("cycles", 0)} for t in open_tasks],
        })

    count = _write_descriptors(session, week, descriptors, open_by_id, goal_by_title, source)
    graph.bus.publish("plan.updated", {"week": week, "tasks": count, "module": "horizon"})
    return {"week": week, "tasks": count, "method": method}


def _write_descriptors(session, week: str, descriptors: list[dict],
                       open_by_id: dict, goal_by_title: dict, source: str) -> int:
    """Apply core plan descriptors to the graph. Carries cycles + smallest_piece
    onto the task so the boredom rule can escalate stuck work next cycle."""
    count = 0
    for d in descriptors:
        extra = {"cycles": d["cycles"], "smallest_piece": d["smallest_piece"]}
        if d["origin"] == "reuse" and d["id"] in open_by_id:
            patch = {"week": week, **extra}
            if d["if_then"]:
                patch["if_then"] = d["if_then"]
            session.update_entity(d["id"], patch, source=source)
        else:
            tid = session.create_entity(
                "task", {"title": d["title"], "if_then": d["if_then"], "status": "open",
                         "week": week, **extra},
                source=source,
            )
            goal_id = goal_by_title.get(d["goal_title"])
            if goal_id:
                session.create_edge(tid, goal_id, "feeds", source=source)
        count += 1
    return count


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


def list_goals(graph: Graph) -> list[dict]:
    """Plan-level goals with their focus flag (for /focus and the app)."""
    session = graph.session("horizon", SCOPES)
    return [{"id": g["id"], "title": g["attrs"].get("title", ""), "focus": bool(g["attrs"].get("focus", False))}
            for g in session.find_entities("goal", {"level": "goal"}, limit=50)]


def set_goal_focus(graph: Graph, goal_id: str, focus: bool = True, source: str = "focus") -> dict:
    """Gate-first: mark (or clear) a goal as this cycle's focus so it leads the plan."""
    session = graph.session("horizon", SCOPES | {"goals:write"})
    session.update_entity(goal_id, {"focus": bool(focus)}, source=source)
    return {"goal_id": goal_id, "focus": bool(focus)}


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
    baseline = cfg.get("vitals", {}).get("energy_baseline", "tired")
    result = plan_week(graph, claude=claude, energy_baseline=baseline)
    print(json.dumps(result))
    print(format_week(graph, result["week"]))


if __name__ == "__main__":
    main()
