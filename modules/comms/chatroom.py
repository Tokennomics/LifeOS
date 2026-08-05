"""Active Outing Chatrooms.

Enables quick status messages and text announcements within a specific outing's active thread.
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


def send_message(
    graph: Graph,
    event_id: str,
    user_id: str,
    message: str,
    caller_id: str | None = None
) -> str:
    """Sends a status message to the active outing chatroom thread."""
    if not event_id.strip() or not user_id.strip() or not message.strip():
        raise ValueError("event_id, user_id, and message are required")

    if not _is_event_visible(graph, event_id, caller_id):
        raise ValueError("access denied: cannot view this event")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "chatroom_message",
        "event_id": event_id,
        "user_id": user_id,
        "message": message
    }
    
    return session.create_entity("content", attrs, source="chatrooms")


def list_messages(graph: Graph, event_id: str, caller_id: str | None = None) -> list[dict]:
    """Lists all messages sent in a specific outing chatroom thread."""
    if not _is_event_visible(graph, event_id, caller_id):
        raise ValueError("access denied: cannot view this event")

    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn
    cur = conn.cursor()

    if session.graph.dialect == "sqlite":
        cur.execute(
            "SELECT id, attrs, created_at FROM entities WHERE kind='content' AND json_extract(attrs, '$.type')='chatroom_message' AND json_extract(attrs, '$.event_id')=?",
            (event_id,)
        )
    else:
        cur.execute(
            "SELECT id, attrs, created_at FROM entities WHERE kind='content' AND attrs->>'type'='chatroom_message' AND attrs->>'event_id'=?",
            (event_id,)
        )

    messages = []
    for row in cur.fetchall():
        r_id, r_attrs_raw, r_created_at = row
        attrs = json.loads(r_attrs_raw) if isinstance(r_attrs_raw, str) else r_attrs_raw
        messages.append({
            "message_id": r_id,
            "user_id": attrs.get("user_id"),
            "message": attrs.get("message"),
            "created_at": r_created_at
        })

    # Sort chronologically
    messages.sort(key=lambda x: x["created_at"] or "")
    return messages

