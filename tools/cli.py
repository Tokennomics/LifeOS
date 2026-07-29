"""LifeOS Command-Line Interface (CLI).

Terminal tool for fast graph capture, weekly plan inspection, triage briefing,
and steward action management.
"""

import argparse
import sys

from modules.horizon import planner
from modules.steward import actions
from modules.triage import brief
from substrate.bus import Bus
from substrate.graph import Graph
from substrate.migrate import migrate


def main(args_list: list[str] | None = None, graph: Graph | None = None) -> int:
    parser = argparse.ArgumentParser(description="LifeOS Terminal CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Capture command
    cap_parser = subparsers.add_parser("capture", help="Quick capture to graph")
    cap_parser.add_argument("text", type=str, help="Captured thought or note")

    # Plan command
    subparsers.add_parser("plan", help="View current week's plan")

    # Triage command
    subparsers.add_parser("triage", help="View daily triage briefing")

    # Steward command
    subparsers.add_parser("steward", help="View open steward items")

    parsed = parser.parse_args(args_list)

    if graph is None:
        conn = migrate({"env": "sqlite", "sqlite": {"path": "lifeos.db"}})
        bus = Bus()
        graph = Graph(conn, bus, default_owner="cli_user")

    if parsed.command == "capture":
        session = graph.session("cli", {"content:read", "content:write"})
        cid = session.create_entity("content", {"type": "capture", "text": parsed.text.strip()}, source="cli")
        print(f"[LifeOS CLI] Captured note: '{parsed.text}' (id: {cid})")
        return 0

    elif parsed.command == "plan":
        tasks = planner.week_tasks(graph)
        print(f"[LifeOS CLI] Current Week Plan ({len(tasks)} tasks):")
        for t in tasks:
            title = t.get("title", "?")
            status = t.get("status", "open")
            print(f"  - [{status.upper()}] {title}")
        return 0

    elif parsed.command == "triage":
        b = brief.generate_triage_brief(graph)
        print("[LifeOS CLI] Daily Triage Briefing:")
        if b.get("escalation"):
            esc = b["escalation"]
            print(f"  * PRIORITY: {esc.get('title')} ({esc.get('reason')})")
        print(f"  * Energy: {b.get('energy', {}).get('baseline')}")
        return 0

    elif parsed.command == "steward":
        items = actions.open_items(graph)
        print(f"[LifeOS CLI] Open Steward Items ({len(items)}):")
        for item in items:
            print(f"  - [{item['type']}] {item['title']}: {item['suggestion']}")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
