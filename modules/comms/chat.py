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
    linked_entity_id: str | None = None
) -> dict:
    """Sends a message, saving it as a content entity in the graph."""
    if not sender_id.strip() or not recipient_id.strip() or not body.strip():
        raise ValueError("sender_id, recipient_id, and body are required")

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


def get_messages(graph: Graph, recipient_id: str) -> list[dict]:
    """Retrieves all chat messages sent to or by a recipient."""
    session = graph.session(MODULE, SCOPES)
    
    entities = session.find_entities("content", limit=500)
    messages = []

    for ent in entities:
        attrs = ent.get("attrs", {})
        if attrs.get("type") == "chat_message":
            if attrs.get("recipient_id") == recipient_id or attrs.get("sender_id") == recipient_id:
                messages.append({
                    "message_id": ent["id"],
                    "sender_id": attrs.get("sender_id"),
                    "recipient_id": attrs.get("recipient_id"),
                    "body": attrs.get("body"),
                    "timestamp": attrs.get("timestamp")
                })

    # Sort chronologically
    messages.sort(key=lambda x: x.get("timestamp", ""))
    return messages
