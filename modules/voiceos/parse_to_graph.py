"""VoiceOS — turn a raw capture into graph entities (not just files).

Extraction runs on the light model (COGS). Extracted entities are linked to the
capture via a `feeds` edge (capture content feeds the derived entity).
"""

from substrate.graph import GraphSession

EXTRACT_SYSTEM = (
    "You extract structure from a captured thought in a personal Life OS. From the text, "
    "pull out: actionable tasks (imperative, concrete), interests (topics/activities the "
    "user cares about), and people mentioned by name. Only extract what is clearly there — "
    "empty lists are correct for a plain note. Keep titles/names short."
)

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {"type": "array", "items": {"type": "string"}},
        "interests": {"type": "array", "items": {"type": "string"}},
        "people": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tasks", "interests", "people"],
    "additionalProperties": False,
}


def apply(session: GraphSession, capture_id: str, data: dict, source: str) -> dict:
    """Write extracted entities + feeds edges. Dedupes people/interests by name."""
    counts = {"tasks": 0, "interests": 0, "people": 0}
    for title in data.get("tasks", []):
        tid = session.create_entity("task", {"title": title, "status": "open", "if_then": ""}, source=source)
        session.create_edge(capture_id, tid, "feeds", source=source)
        counts["tasks"] += 1
    for name in data.get("interests", []):
        counts["interests"] += _link_named(session, capture_id, "interest", name, source)
    for name in data.get("people", []):
        counts["people"] += _link_named(session, capture_id, "person", name, source)
    return counts


def _link_named(session: GraphSession, capture_id: str, kind: str, name: str, source: str) -> int:
    existing = session.find_entities(kind, {"name": name}, limit=1)
    eid = existing[0]["id"] if existing else session.create_entity(kind, {"name": name}, source=source)
    session.create_edge(capture_id, eid, "feeds", source=source)
    return 0 if existing else 1
