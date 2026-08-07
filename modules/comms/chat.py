"""Semantic Chat & Comms Hub.

Integrates direct messaging inside the graph substrate and links chat messages to entities.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "*"}
MODULE = "comms"


def send_message(
    graph: Graph,
    sender_id: str,
    recipient_id: str,
    body: str,
    linked_entity_id: str | None = None,
    caller_id: str | None = None
) -> dict:
    """Sends a message, saving it as a content entity in the graph."""
    if not sender_id.strip() or not recipient_id.strip() or not body.strip():
        raise ValueError("sender_id, recipient_id, and body are required")

    if caller_id and sender_id != caller_id:
        raise ValueError("access denied: cannot send message as another user")

    session = graph.session(MODULE, SCOPES)
    
    attrs = {
        "type": "chat_message",
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "body": body,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    msg_id = session.create_entity("content", attrs, source="chat_hub")
    
    # If there is a linked entity, build a feeds edge
    if linked_entity_id:
        try:
            session.create_edge(msg_id, linked_entity_id, "feeds", source="chat_hub")
        except Exception:
            pass

    return {
        "message_id": msg_id,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "body": body,
        "linked_entity_id": linked_entity_id
    }


def get_messages(graph: Graph, recipient_id: str, caller_id: str | None = None) -> list[dict]:
    """Retrieves all chat messages sent to or by a recipient."""
    if caller_id and recipient_id != caller_id:
        raise ValueError("access denied: cannot view another user's messages")

    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn
    cur = conn.cursor()

    if session.graph.dialect == "sqlite":
        cur.execute(
            "SELECT id, attrs, created_at FROM entities WHERE kind='content' AND json_extract(attrs, '$.type')='chat_message' AND (json_extract(attrs, '$.sender_id')=? OR json_extract(attrs, '$.recipient_id')=?)",
            (recipient_id, recipient_id)
        )
    else:
        cur.execute(
            "SELECT id, attrs, created_at FROM entities WHERE kind='content' AND attrs->>'type'='chat_message' AND (attrs->>'sender_id'=? OR attrs->>'recipient_id'=?)",
            (recipient_id, recipient_id)
        )

    messages = []
    for row in cur.fetchall():
        import json
        r_id, r_attrs_raw, r_created_at = row
        attrs = json.loads(r_attrs_raw) if isinstance(r_attrs_raw, str) else r_attrs_raw
        messages.append({
            "message_id": r_id,
            "sender_id": attrs.get("sender_id"),
            "recipient_id": attrs.get("recipient_id"),
            "body": attrs.get("body"),
            "timestamp": attrs.get("timestamp")
        })

    # Sort chronologically
    messages.sort(key=lambda x: x.get("timestamp") or "")
    return messages

