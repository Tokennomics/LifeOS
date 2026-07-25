"""Crews — create/join/browse named groups (topic + city + members)."""

from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "people:read"}
MODULE = "crews"


def _norm(s: str, cap: int = 80) -> str:
    return str(s or "").strip()[:cap]


def _key(s: str) -> str:
    """Case/space-insensitive match key, so 'Climbing' == 'climbing'."""
    return _norm(s).lower()


def _load(session, crew_id: str) -> dict:
    crew = session.get_entity(crew_id)
    if crew is None or crew["kind"] != "content" or crew["attrs"].get("type") != "crew":
        raise ValueError("unknown crew")
    return crew


def _view(session, crew: dict) -> dict:
    a = crew["attrs"]
    members = []
    for grant in session.grants_for(crew["id"]):
        if grant["scope"] != "crew:member":
            continue
        person = session.get_entity(grant["subject"])
        if person:
            members.append({"id": person["id"], "name": person["attrs"].get("name", "?")})
    return {"id": crew["id"], "name": a.get("name", "?"), "topic": a.get("topic", ""),
            "city": a.get("city", ""), "members": members, "member_count": len(members)}


def create(graph: Graph, name: str, topic: str = "", city: str = "",
           member_ids: list[str] | None = None, source: str = MODULE) -> dict:
    name, topic, city = _norm(name), _norm(topic, 40), _norm(city, 60)
    if not name:
        raise ValueError("a crew needs a name")
    session = graph.session(MODULE, SCOPES)
    for existing in session.find_entities("content", {"type": "crew"}, limit=200):
        if _key(existing["attrs"].get("name")) == _key(name):
            raise ValueError(f"crew {name!r} already exists")

    crew_id = session.create_entity(
        "content", {"type": "crew", "name": name, "topic": topic, "city": city}, source=source)
    for pid in member_ids or []:
        _grant(session, crew_id, pid, source)
    return _view(session, _load(session, crew_id))


def _grant(session, crew_id: str, person_id: str, source: str) -> bool:
    person = session.get_entity(person_id)
    if person is None or person["kind"] != "person":
        return False
    already = any(g["subject"] == person_id and g["scope"] == "crew:member"
                  for g in session.grants_for(crew_id))
    if already:
        return False
    session.grant(person_id, "crew:member", crew_id, source=source)
    return True


def join(graph: Graph, crew_id: str, person_id: str, source: str = MODULE) -> dict:
    """Add a person to a crew (idempotent)."""
    session = graph.session(MODULE, SCOPES)
    crew = _load(session, crew_id)
    added = _grant(session, crew_id, person_id, source)
    if not added and not any(g["subject"] == person_id for g in session.grants_for(crew_id)):
        raise ValueError("unknown person")
    return {**_view(session, crew), "added": added}


def members(graph: Graph, crew_id: str) -> list[str]:
    session = graph.session(MODULE, SCOPES)
    return [m["id"] for m in _view(session, _load(session, crew_id))["members"]]


def get(graph: Graph, crew_id: str) -> dict:
    session = graph.session(MODULE, SCOPES)
    return _view(session, _load(session, crew_id))


def browse(graph: Graph, topic: str = "", city: str = "", limit: int = 50) -> list[dict]:
    """Directory-shaped read: filter by topic and/or city (both optional, case-insensitive).

    Local-only today; the same signature is what a future cross-user directory would expose.
    """
    session = graph.session(MODULE, SCOPES)
    out = []
    for crew in session.find_entities("content", {"type": "crew"}, limit=limit):
        a = crew["attrs"]
        if topic and _key(a.get("topic")) != _key(topic):
            continue
        if city and _key(a.get("city")) != _key(city):
            continue
        out.append(_view(session, crew))
    out.sort(key=lambda c: (-c["member_count"], c["name"]))
    return out
