"""Live Crew Photo Collage Creator.

Aggregates outing gallery photos and memory capsules into structured collages.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "comms"


import json

def _is_event_visible(graph: Graph, event_id: str, caller_id: str | None) -> bool:
    if not caller_id:
        return True
    cur = graph.conn.cursor()
    cur.execute("SELECT owner_id, attrs FROM entities WHERE id=?", (event_id,))
    row = cur.fetchone()
    if not row:
        return False
    owner_id, attrs_raw = row
    attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) else attrs_raw
    if graph.default_owner and owner_id == graph.default_owner:
        return True
    if attrs.get("visibility") == "public":
        return True
    crew_id = attrs.get("crew_id")
    if crew_id:
        from modules.crews import crews
        try:
            m_list = crews.members(graph, crew_id, caller_id)
            if caller_id in m_list:
                return True
        except Exception:
            pass
    if caller_id in attrs.get("invited", []) or caller_id in attrs.get("yes", []):
        return True
    return False


def create_photo_collage(
    graph: Graph,
    event_id: str,
    caller_id: str | None = None
) -> list[dict]:
    """Generates a structured collage layout representation of outing photo URLs."""
    if not _is_event_visible(graph, event_id, caller_id):
        raise ValueError("access denied: cannot view this event")

    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn
    cur = conn.cursor()

    if session.graph.dialect == "sqlite":
        cur.execute(
            "SELECT id, attrs, created_at FROM entities WHERE kind='content' AND json_extract(attrs, '$.type')='shared_photo' AND json_extract(attrs, '$.event_id')=?",
            (event_id,)
        )
    else:
        cur.execute(
            "SELECT id, attrs, created_at FROM entities WHERE kind='content' AND attrs->>'type'='shared_photo' AND attrs->>'event_id'=?",
            (event_id,)
        )

    photos = []
    for row in cur.fetchall():
        r_id, r_attrs_raw, r_created_at = row
        attrs = json.loads(r_attrs_raw) if isinstance(r_attrs_raw, str) else r_attrs_raw
        photos.append({
            "photo_id": r_id,
            "url": attrs.get("photo_url"),
            "owner_id": attrs.get("owner_id"),
            "created_at": r_created_at
        })

    # Sort photos chronologically
    photos.sort(key=lambda x: x["created_at"] or "")
    return photos

