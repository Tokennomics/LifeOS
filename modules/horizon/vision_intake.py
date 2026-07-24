"""Horizon — vision intake: turn a vision statement into a life plan in the graph.

Graph shape (extends via attrs only — schema is FINAL):
  goal(level=vision)  <-feeds-  goal(level=goal)  <-feeds-  goal(level=milestone)
  goal(level=goal)    <-feeds-  task(title, if_then)

CLI:  python -m modules.horizon.vision_intake [--offline] [--config path] "your vision text"
"""

import argparse
import json
import sys

from substrate.graph import Graph

SCOPES = {"goals:read", "goals:write", "tasks:read", "tasks:write"}

SYSTEM = (
    "You are Horizon, the trajectory engine of a personal Life OS. You backcast: from a "
    "vision of where the user wants to be, derive 2-5 concrete goals for the next 12 weeks "
    "(unless the user implies another horizon), each with a short 'why' tied to the vision, "
    "1-3 milestones (checkpoints), and 1-3 immediate tasks. Every task gets an if-then "
    "implementation intention ('If <situation/time>, then I <action>') — these roughly double "
    "follow-through. Prefer behavior the user controls over outcomes they don't. "
    "If the vision is too thin to plan honestly, return status='questions' with at most 3 "
    "sharp questions instead of guessing. Otherwise return status='plan' with questions=[]. "
    "Titles are short; 'why' is one sentence."
)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["plan", "questions"]},
        "questions": {"type": "array", "items": {"type": "string"}},
        "vision": {"type": "string"},
        "goals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "why": {"type": "string"},
                    "horizon_weeks": {"type": "integer"},
                    "milestones": {"type": "array", "items": {"type": "string"}},
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "if_then": {"type": "string"},
                            },
                            "required": ["title", "if_then"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "why", "horizon_weeks", "milestones", "tasks"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "questions", "vision", "goals"],
    "additionalProperties": False,
}


def intake(text: str, graph: Graph, claude=None, source: str = "vision_intake") -> dict:
    """Parse a vision statement (Claude when available, heuristic otherwise) and write the plan."""
    if claude is not None and claude.available:
        data = claude.complete_json(SYSTEM, text, schema=PLAN_SCHEMA)
        method = "claude"
    else:
        data = _offline_plan(text)
        method = "offline"

    if data["status"] == "questions":
        return {"status": "questions", "questions": data["questions"], "method": method}

    session = graph.session("horizon", SCOPES)
    vision_id = session.create_entity(
        "goal", {"level": "vision", "title": data["vision"]}, source=source,
        confidence=1.0 if method == "claude" else 0.6,
    )
    goal_count = milestone_count = task_count = 0
    for goal in data["goals"]:
        gid = session.create_entity(
            "goal",
            # First goal is the default focus (gate-first): you write the goal the
            # current gate depends on first. Retarget later via set_goal_focus.
            {"level": "goal", "title": goal["title"], "why": goal.get("why", ""),
             "horizon_weeks": goal.get("horizon_weeks", 12), "focus": goal_count == 0},
            source=source,
        )
        session.create_edge(gid, vision_id, "feeds", source=source)
        goal_count += 1
        for milestone in goal.get("milestones", []):
            mid = session.create_entity(
                "goal", {"level": "milestone", "title": milestone}, source=source,
            )
            session.create_edge(mid, gid, "feeds", source=source)
            milestone_count += 1
        for task in goal.get("tasks", []):
            tid = session.create_entity(
                "task", {"title": task["title"], "if_then": task.get("if_then", ""), "status": "open"},
                source=source,
            )
            session.create_edge(tid, gid, "feeds", source=source)
            task_count += 1

    graph.bus.publish("plan.updated", {"vision_id": vision_id, "goals": goal_count, "module": "horizon"})
    return {
        "status": "created",
        "method": method,
        "vision_id": vision_id,
        "vision": data["vision"],
        "goals": goal_count,
        "milestones": milestone_count,
        "tasks": task_count,
    }


def _offline_plan(text: str) -> dict:
    """Deterministic fallback: first line = vision, bulleted/remaining lines = goals."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return {"status": "questions", "vision": "", "goals": [],
                "questions": ["Where do you want to be, and by when?"]}
    vision, rest = lines[0], lines[1:]
    bullets = [line.lstrip("-*0123456789. ").strip() for line in rest]
    goals = [
        {"title": b, "why": "", "horizon_weeks": 12, "milestones": [], "tasks": []}
        for b in bullets if b
    ]
    return {"status": "plan", "vision": vision, "goals": goals, "questions": []}


def format_summary(result: dict) -> str:
    if result["status"] == "questions":
        qs = "\n".join(f"- {q}" for q in result["questions"])
        return f"Before I plan, answer me this:\n{qs}"
    return (
        f"Plan created ({result['method']}): \"{result['vision']}\"\n"
        f"{result['goals']} goals, {result['milestones']} milestones, {result['tasks']} tasks "
        f"written to the graph."
    )


def main():
    from gateway.claude import ClaudeGateway
    from substrate import load_config
    from substrate.migrate import migrate

    parser = argparse.ArgumentParser(description="Horizon vision intake")
    parser.add_argument("text", nargs="?", help="vision text (or pipe via stdin)")
    parser.add_argument("--config", default=None)
    parser.add_argument("--offline", action="store_true", help="skip Claude, use heuristic parse")
    args = parser.parse_args()

    text = args.text or sys.stdin.read()
    if not text.strip():
        sys.exit("No vision text given.")
    cfg = load_config(args.config)
    graph = Graph(migrate(cfg), default_owner=cfg.get("owner", {}).get("id"))
    claude = None if args.offline else ClaudeGateway(cfg)
    result = intake(text, graph, claude=claude)
    print(json.dumps(result, indent=2))
    print(format_summary(result))


if __name__ == "__main__":
    main()
