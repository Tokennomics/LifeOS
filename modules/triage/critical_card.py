"""Triage OS — Static Critical-Info Card (Medical ID Equivalent).

Offline-accessible card storing emergency contacts, blood type, allergies,
and medical notes directly in the graph. Never dispatches or contacts third parties.
"""

from substrate.graph import Graph

SCOPES = {"content:read", "content:write"}


def save_critical_card(graph: Graph, data: dict, source: str = "triage") -> dict:
    """Saves or updates the static critical info card."""
    session = graph.session("triage", SCOPES)
    existing = session.find_entities("content", {"type": "critical_card"}, limit=1)

    card_attrs = {
        "type": "critical_card",
        "full_name": str(data.get("full_name", "")).strip(),
        "blood_type": str(data.get("blood_type", "")).strip(),
        "allergies": str(data.get("allergies", "")).strip(),
        "notes": str(data.get("notes", "")).strip(),
        "emergency_contacts": list(data.get("emergency_contacts", [])),
    }

    if existing:
        card_id = existing[0]["id"]
        session.update_entity(card_id, card_attrs, source=source)
    else:
        card_id = session.create_entity("content", card_attrs, source=source)

    card_attrs["id"] = card_id
    return card_attrs


def get_critical_card(graph: Graph) -> dict:
    """Fetches the static critical info card if configured."""
    session = graph.session("triage", SCOPES)
    existing = session.find_entities("content", {"type": "critical_card"}, limit=1)
    if not existing:
        return {"configured": False, "card": {}}

    item = existing[0]
    attrs = dict(item.get("attrs", {}))
    attrs["id"] = item["id"]
    return {"configured": True, "card": attrs}
