"""Horizon — Sunday retro: score the week (monitor behavior AND outcomes), write a metric, reflect.

CLI:  python -m modules.horizon.retro [--offline] [--config path]
"""

import argparse
import json

from modules.horizon import core
from modules.horizon.planner import week_id, week_tasks
from substrate.graph import Graph

SCOPES = {"goals:read", "tasks:read", "metrics:read", "metrics:write"}

RETRO_SYSTEM = (
    "You are Horizon's weekly retro coach in a personal Life OS. Given this week's planned "
    "tasks and completion stats, write a short reflection (max 100 words): name what worked, "
    "name the biggest miss without moralizing, and suggest ONE adjustment for next week's "
    "plan. Direct, warm, no filler."
)


def run_retro(graph: Graph, claude=None, week: str | None = None, source: str = "retro") -> dict:
    week = week or week_id()
    tasks = week_tasks(graph, week)
    task_views = [{"title": t["attrs"].get("title", ""), "status": t["attrs"].get("status", "open")}
                  for t in tasks]
    scored = core.retro(week, task_views)  # shared with Travel Mode — one scoring path
    planned, done, rate = scored["planned"], scored["done"], scored["rate"]

    session = graph.session("horizon", SCOPES)
    session.create_entity(
        "metric",
        {"type": "weekly_retro", "week": week, "planned": planned, "done": done, "rate": rate},
        source=source,
    )

    text = scored["text"]
    if claude is not None and claude.available and planned:
        stats = json.dumps({
            "week": week, "planned": planned, "done": done, "rate": rate,
            "tasks": task_views,
        })
        text += "\n" + claude.complete(RETRO_SYSTEM, stats, max_tokens=1024).strip()

    return {"week": week, "planned": planned, "done": done, "rate": rate, "text": text}


def main():
    from gateway.claude import ClaudeGateway
    from substrate import load_config
    from substrate.migrate import migrate

    parser = argparse.ArgumentParser(description="Horizon weekly retro")
    parser.add_argument("--config", default=None)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.config)
    graph = Graph(migrate(cfg), default_owner=cfg.get("owner", {}).get("id"))
    claude = None if args.offline else ClaudeGateway(cfg)
    result = run_retro(graph, claude=claude)
    print(result["text"])


if __name__ == "__main__":
    main()
