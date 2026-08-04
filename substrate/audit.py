"""Graph Log Audit Timeline.

Aggregates entity mutations to output a chronological timeline of database actions.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def generate_audit_timeline(graph: Graph) -> list[dict]:
    """Generates a history timeline of all created entities."""
    session = graph.session(MODULE, SCOPES)
    
    kinds = ["admin_item", "content", "decision", "event", "goal", "interest", "memory", "metric", "person", "place", "task"]
    timeline = []
    
    for k in kinds:
        try:
            entities = session.find_entities(k, limit=100)
            for ent in entities:
                attrs = ent.get("attrs", {})
                label = attrs.get("name") or attrs.get("title") or attrs.get("type") or "Unknown"
                timeline.append({
                    "entity_id": ent["id"],
                    "kind": ent["kind"],
                    "label": label,
                    "created_at": ent["created_at"]
                })
        except Exception:
            pass

    timeline.sort(key=lambda x: x["created_at"])
    return timeline
