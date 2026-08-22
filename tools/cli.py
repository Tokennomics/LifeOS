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

    # Export command
    exp_parser = subparsers.add_parser("export", help="Export Universal Markdown Vault (.zip)")
    exp_parser.add_argument("--format", type=str, default="Obsidian", help="Vault format (Obsidian, Notion, AppleNotes)")
    exp_parser.add_argument("--output", type=str, default="lifeos_vault.zip", help="Target zip filename")

    # Daily synthesize command
    subparsers.add_parser("synthesize", help="Run Daily Midnight Reflection Synthesis")

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

    elif parsed.command == "export":
        from modules.backup import universal_markdown
        import base64
        res = universal_markdown.export_markdown_vault(graph, format_type=parsed.format)
        b64_data = res["download_url"].split("base64,")[1]
        zip_bytes = base64.b64decode(b64_data)
        with open(parsed.output, "wb") as f:
            f.write(zip_bytes)
        print(f"[LifeOS CLI] Exported {res['total_vault_files']} notes across 11 graph kinds to '{parsed.output}' ({res['format']})! 📦")
        return 0

    elif parsed.command == "synthesize":
        # Pointed at `personal.journal`, which reads your own check-ins, moments and notes.
        # The module this replaced branched on the city name — "Munich" produced dawn surfers
        # on the Eisbach and gratitude to a man called Lukas — and then *wrote that day into
        # the graph* as a sealed memory with a presence score. A fabricated day that is
        # merely displayed is bad; one that is persisted becomes indistinguishable from a
        # real one on every screen that reads memories afterwards.
        from modules.personal import journal
        res = journal.day(graph)
        if res["empty"]:
            print("[LifeOS CLI] Nothing recorded today. " + res["suggestion"])
            return 0
        print(f"[LifeOS CLI] {res['date']} — {res['summary']}")
        for line in res["did"]:
            print(f"  · {line}")
        for note in res["notes"]:
            print(f"  \u201c{note}\u201d")
        print(f"  ({len(res['sources'])} entries of your own)")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
