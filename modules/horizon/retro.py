"""Horizon — Sunday retro: score the week (monitor behavior AND outcomes), write a metric, reflect.

CLI:  python -m modules.horizon.retro [--offline] [--config path]
"""

import argparse
import json

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
    done = [t for t in tasks if t["attrs"].get("status") == "done"]
    planned = len(tasks)
    rate = round(len(done) / planned, 2) if planned else 0.0

    session = graph.session("horizon", SCOPES)
    session.create_entity(
        "metric",
        {"type": "weekly_retro", "week": week, "planned": planned, "done": len(done), "rate": rate},
        source=source,
    )

    lines = [f"Retro {week}: {len(done)}/{planned} tasks done ({int(rate * 100)}%)."]
    for t in tasks:
        mark = "x" if t["attrs"].get("status") == "done" else " "
        lines.append(f"[{mark}] {t['attrs'].get('title', '')}")

    if claude is not None and claude.available and planned:
        stats = json.dumps({
            "week": week, "planned": planned, "done": len(done), "rate": rate,
            "tasks": [{"title": t["attrs"].get("title"), "status": t["attrs"].get("status")} for t in tasks],
        })
        lines.append(claude.complete(RETRO_SYSTEM, stats, max_tokens=1024).strip())
    elif planned == 0:
        lines.append("Nothing was planned this week — send /plan on Monday (or now).")

    return {"week": week, "planned": planned, "done": len(done), "rate": rate, "text": "\n".join(lines)}


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
