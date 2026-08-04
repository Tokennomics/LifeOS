"""Active Outing Chatrooms.

Enables quick status messages and text announcements within a specific outing's active thread.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "comms"


def send_message(
    graph: Graph,
    event_id: str,
    user_id: str,
    message: str
) -> str:
    """Sends a status message to the active outing chatroom thread."""
    if not event_id.strip() or not user_id.strip() or not message.strip():
        raise ValueError("event_id, user_id, and message are required")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "chatroom_message",
        "event_id": event_id,
        "user_id": user_id,
        "message": message
    }
    
    return session.create_entity("content", attrs, source="chatrooms")


def list_messages(graph: Graph, event_id: str) -> list[dict]:
    """Lists all messages sent in a specific outing chatroom thread."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("content", limit=1000)

    messages = []
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "chatroom_message" and attrs.get("event_id") == event_id:
            messages.append({
                "message_id": item["id"],
                "user_id": attrs.get("user_id"),
                "message": attrs.get("message"),
                "created_at": item["created_at"]
            })

    # Sort chronologically
    messages.sort(key=lambda x: x["created_at"])
    return messages
