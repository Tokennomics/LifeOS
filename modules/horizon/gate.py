"""Horizon — /gate: honest v0.1-gate progress (the doubt rule, T3).

Purpose: when doubt shows up while tired, check the metric instead of re-deciding
whether the whole thing is worth it. Every number here is a real count from stored
data — days actually used, logs actually recorded, retros actually completed —
never an estimate.

The v0.1 gate is self-use: run your week daily for four weeks before building any
new surface (README "v0.1 gate"; master doc risk register #2).
"""

import argparse
import json

from modules.horizon import core
from substrate.graph import Graph

SCOPES = {"tasks:read", "content:read", "metrics:read"}


def _day(ts: str) -> str:
    return (ts or "")[:10]  # YYYY-MM-DD from an ISO timestamp


def gate_status(graph: Graph) -> dict:
    """Count real self-use: distinct active days, logged tasks, completed retros."""
    session = graph.session("horizon", SCOPES)
    done = [t for t in session.find_entities("task", limit=1000)
            if t["attrs"].get("status") == "done"]
    captures = session.find_entities("content", limit=1000)
    retros = session.find_entities("metric", {"type": "weekly_retro"}, limit=1000)

    days: set[str] = set()
    for t in done:
        days.add(_day(t["attrs"].get("done_at") or t.get("created_at", "")))
    for c in captures:
        days.add(_day(c.get("created_at", "")))
    for r in retros:
        days.add(_day(r.get("created_at", "")))
    days.discard("")

    return core.gate_from_counts(len(days), len(done), len(retros))


def main():
    from substrate import load_config
    from substrate.migrate import migrate

    parser = argparse.ArgumentParser(description="Horizon v0.1 gate status")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    graph = Graph(migrate(cfg), default_owner=cfg.get("owner", {}).get("id"))
    result = gate_status(graph)
    print(json.dumps(result))
    print(result["text"])


if __name__ == "__main__":
    main()
