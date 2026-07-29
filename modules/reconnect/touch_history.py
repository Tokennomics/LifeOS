"""Reconnect — Relationship Touch History & Context Notes.

Tracks full timeline of interaction events and relationship context notes per person.
"""

from substrate.graph import Graph

SCOPES = {"people:read", "people:write", "events:read", "content:read"}


def get_touch_history(graph: Graph, person_id: str) -> dict:
    """Fetches relationship timeline and context notes for a person."""
    session = graph.session("reconnect", SCOPES)
    person = session.get_entity(person_id)
    if person is None or person["kind"] != "person":
        raise ValueError(f"Person not found: {person_id}")

    p_attrs = person.get("attrs", {})
    name = p_attrs.get("name", "Unknown")
    last_contact = p_attrs.get("last_contact", "")
    cadence_days = p_attrs.get("cadence_days", 30)
    notes = p_attrs.get("notes", [])

    # Find edges pointing to this person
    all_events = session.find_entities("event", limit=500)
    touch_events = []

    for ev in all_events:
        # Check if there is an edge from event to person
        neighbors = session.neighbors(ev["id"], rel="with", direction="out")
        if any(n["id"] == person_id for n in neighbors):
            touch_events.append({
                "id": ev["id"],
                "type": ev.get("attrs", {}).get("type", "touch"),
                "start": ev.get("attrs", {}).get("start") or ev.get("created_at", ""),
                "title": ev.get("attrs", {}).get("title", "Contact event"),
            })

    touch_events.sort(key=lambda e: e["start"], reverse=True)

    return {
        "person_id": person_id,
        "name": name,
        "last_contact": last_contact,
        "cadence_days": cadence_days,
        "notes": notes,
        "total_touches": len(touch_events),
        "history": touch_events,
    }


def add_person_note(graph: Graph, person_id: str, note: str, source: str = "reconnect") -> dict:
    """Adds a context note to a person entity."""
    if not note.strip():
        raise ValueError("note cannot be empty")

    session = graph.session("reconnect", SCOPES)
    person = session.get_entity(person_id)
    if person is None or person["kind"] != "person":
        raise ValueError(f"Person not found: {person_id}")

    existing_notes = list(person.get("attrs", {}).get("notes", []))
    existing_notes.append(note.strip())

    session.update_entity(person_id, {"notes": existing_notes}, source=source)
    return {"person_id": person_id, "notes_count": len(existing_notes), "added_note": note.strip()}
