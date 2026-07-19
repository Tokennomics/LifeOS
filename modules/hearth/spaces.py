"""Hearth — shared-graph spaces P0: the ACL'd data model (household/family sync builds on this).

A space is a content entity; membership is grants rows (subject=person, space=space_id).
Multi-device sync and per-space subgraph filtering arrive with the postgres era.
"""

from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "people:read"}


def create_space(graph: Graph, name: str, member_ids: list[str] | None = None,
                 source: str = "hearth") -> dict:
    session = graph.session("hearth", SCOPES)
    if session.find_entities("content", {"type": "space", "name": name}, limit=1):
        raise ValueError(f"space {name!r} already exists")
    space_id = session.create_entity("content", {"type": "space", "name": name}, source=source)
    added = 0
    for pid in member_ids or []:
        person = session.get_entity(pid)
        if person and person["kind"] == "person":
            session.grant(pid, "space:member", space_id, source=source)
            added += 1
    return {"space_id": space_id, "name": name, "members": added}


def add_member(graph: Graph, space_id: str, person_id: str, source: str = "hearth") -> dict:
    session = graph.session("hearth", SCOPES)
    space = session.get_entity(space_id)
    if space is None or space["attrs"].get("type") != "space":
        raise ValueError("unknown space")
    session.grant(person_id, "space:member", space_id, source=source)
    return {"space_id": space_id, "person_id": person_id}


def spaces(graph: Graph) -> list[dict]:
    session = graph.session("hearth", SCOPES)
    out = []
    for space in session.find_entities("content", {"type": "space"}, limit=50):
        members = session.grants_for(space["id"])
        names = []
        for grant in members:
            person = session.get_entity(grant["subject"])
            if person:
                names.append(person["attrs"].get("name", "?"))
        out.append({"id": space["id"], "name": space["attrs"].get("name", "?"), "members": names})
    return out
