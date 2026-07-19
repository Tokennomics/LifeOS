"""Reconnect — decay detection: which existing friendships are going stale.

Friendship = hours (Hall). last_contact moves whenever ANY module records contact
(a Convoy attendance, a reconnect touch) — cross-module compounding by design.
"""

import datetime

from substrate.graph import Graph

SCOPES = {"people:read", "people:write", "events:read", "events:write"}
DEFAULT_CADENCE_DAYS = 30


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def ranked(graph: Graph, limit: int = 20) -> list[dict]:
    """People sorted by how overdue contact is (overdue >= 1.0 means past cadence)."""
    session = graph.session("reconnect", SCOPES)
    now = _now()
    out = []
    for person in session.find_entities("person", limit=200):
        attrs = person["attrs"]
        anchor = attrs.get("last_contact") or person["created_at"]
        try:
            days = max(0.0, (now - datetime.datetime.fromisoformat(anchor)).total_seconds() / 86400)
        except (ValueError, TypeError):
            days = 0.0
        cadence = attrs.get("cadence_days", DEFAULT_CADENCE_DAYS)
        out.append({
            "id": person["id"],
            "name": attrs.get("name", "?"),
            "days_since": round(days, 1),
            "cadence_days": cadence,
            "overdue": round(days / cadence, 2) if cadence else 0.0,
        })
    out.sort(key=lambda p: p["overdue"], reverse=True)
    return out[:limit]


def add_person(graph: Graph, name: str, cadence_days: int = DEFAULT_CADENCE_DAYS,
               source: str = "reconnect") -> str:
    session = graph.session("reconnect", SCOPES)
    existing = session.find_entities("person", {"name": name}, limit=1)
    if existing:
        return existing[0]["id"]
    return session.create_entity(
        "person", {"name": name, "cadence_days": cadence_days, "last_contact": _now().isoformat()},
        source=source,
    )


def touch(graph: Graph, person_id: str, kind: str = "reconnect", source: str = "reconnect") -> dict:
    """Record executed contact: bumps last_contact + writes a touch event `with` the person.

    This is the gate metric (>=1 executed reconnect/wk) — countable from events.
    """
    session = graph.session("reconnect", SCOPES)
    person = session.get_entity(person_id)
    if person is None or person["kind"] != "person":
        raise ValueError("unknown person")
    now = _now().isoformat()
    session.update_entity(person_id, {"last_contact": now}, source=source)
    event_id = session.create_entity("event", {"type": f"{kind}_touch", "start": now}, source=source)
    session.create_edge(event_id, person_id, "with", source=source)
    graph.bus.publish("event.attended", {"event_id": event_id, "person_id": person_id, "module": "reconnect"})
    return {"person": person["attrs"].get("name"), "event_id": event_id}
