"""Notification Dispatcher — Multi-Channel Notification Queue.

Formats and queues high-priority alerts (dead-man's switch, triage escalations,
crew invites) for delivery via Web Push, Telegram, or Webhooks.
"""

from substrate.graph import Graph

SCOPES = {"content:read", "content:write"}
VALID_CHANNELS = {"web_push", "telegram", "webhook"}


def enqueue_notification(graph: Graph, channel: str, recipient: str, title: str, body: str,
                         source: str = "notifications") -> dict:
    """Enqueues a notification into the delivery queue."""
    if channel not in VALID_CHANNELS:
        raise ValueError(f"invalid channel '{channel}', must be one of {VALID_CHANNELS}")
    if not recipient.strip() or not title.strip():
        raise ValueError("recipient and title required")

    session = graph.session("notifications", SCOPES)
    nid = session.create_entity(
        "content",
        {
            "type": "notification_queue",
            "channel": channel,
            "recipient": recipient.strip(),
            "title": title.strip(),
            "body": body.strip(),
            "status": "pending",
        },
        source=source,
    )
    graph.bus.publish("notification.enqueued", {"id": nid, "channel": channel, "recipient": recipient, "module": "notifications"})
    return {"id": nid, "channel": channel, "recipient": recipient, "status": "pending"}


def dispatch_pending(graph: Graph) -> dict:
    """Processes pending notifications in the delivery queue."""
    session = graph.session("notifications", SCOPES)
    pending = session.find_entities("content", {"type": "notification_queue", "status": "pending"}, limit=100)

    dispatched_count = 0
    dispatched_ids = []
    for item in pending:
        attrs = item.get("attrs", {})
        attrs["status"] = "dispatched"
        session.update_entity(item["id"], attrs, source="notifications")
        dispatched_count += 1
        dispatched_ids.append(item["id"])

    return {"dispatched_count": dispatched_count, "dispatched_ids": dispatched_ids}
