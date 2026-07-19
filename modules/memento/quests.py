"""Memento — quests P0: attended Convoy events with no capsule yet become drop suggestions.

Convoy events auto-spawn Memento quests (master doc v0.3) — pure graph read, no state.
"""

from substrate.graph import Graph

SCOPES = {"events:read", "memories:read"}


def suggestions(graph: Graph, limit: int = 5) -> list[dict]:
    session = graph.session("memento", SCOPES)
    capsules = session.find_entities("memory", {"type": "capsule"}, limit=200)
    capsule_events = {c["attrs"].get("event_id") for c in capsules if c["attrs"].get("event_id")}
    out = []
    for event in session.find_entities("event", {"type": "social"}, limit=100):
        if event["attrs"].get("status") != "attended" or event["id"] in capsule_events:
            continue
        out.append({
            "event_id": event["id"],
            "title": event["attrs"].get("title", "?"),
            "prompt": f"You were at '{event['attrs'].get('title', '?')}' — drop a capsule so the place remembers.",
        })
    return out[:limit]
