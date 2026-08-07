"""P2P Outing Group Announcement Board.

Publishes pinned notices and crew-wide notifications.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "comms"


def publish_bulletin(
    graph: Graph,
    crew_id: str,
    title: str,
    body: str,
    caller_id: str | None = None
) -> str:
    """Publishes a new announcement board bulletin pinned to a crew."""
    if not crew_id.strip() or not title.strip():
        raise ValueError("crew_id and title are required")

    if caller_id:
        from modules.crews import crews
        try:
            m_list = crews.members(graph, crew_id, caller_id)
            if caller_id not in m_list:
                raise ValueError("only crew members can publish bulletins")
        except Exception:
            raise ValueError("access denied: not a member of this crew")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "bulletin_announcement",
        "crew_id": crew_id,
        "title": title,
        "body": body
    }
    
    return session.create_entity("content", attrs, source="bulletins")


def list_bulletins(graph: Graph, crew_id: str, caller_id: str | None = None) -> list[dict]:
    """Lists all active bulletins pinned to a target crew."""
    if caller_id:
        from modules.crews import crews
        try:
            # Enforce access check
            crews.members(graph, crew_id, caller_id)
        except Exception:
            raise ValueError("access denied: not a member of this crew")

    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn
    cur = conn.cursor()

    if session.graph.dialect == "sqlite":
        cur.execute(
            "SELECT id, attrs, created_at FROM entities WHERE kind='content' AND json_extract(attrs, '$.type')='bulletin_announcement' AND json_extract(attrs, '$.crew_id')=?",
            (crew_id,)
        )
    else:
        cur.execute(
            "SELECT id, attrs, created_at FROM entities WHERE kind='content' AND attrs->>'type'='bulletin_announcement' AND attrs->>'crew_id'=?",
            (crew_id,)
        )

    bulletins = []
    for row in cur.fetchall():
        import json
        r_id, r_attrs_raw, r_created_at = row
        attrs = json.loads(r_attrs_raw) if isinstance(r_attrs_raw, str) else r_attrs_raw
        bulletins.append({
            "bulletin_id": r_id,
            "title": attrs.get("title"),
            "body": attrs.get("body"),
            "created_at": r_created_at
        })

    bulletins.sort(key=lambda x: x.get("created_at") or "")
    return bulletins

