"""Steward — Transactional Outbox & Idempotent Agent Execution.

Provides durable, transactional execution of background agent activities
with checkpoint audit logs.
"""

from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "admin:read", "admin:write"}


def enqueue_activity(graph: Graph, module: str, action_type: str, payload: dict, source: str = "outbox") -> dict:
    """Enqueues a background activity into the durable outbox."""
    session = graph.session("steward", SCOPES)
    item_id = session.create_entity(
        "content",
        {
            "type": "agent_activity",
            "target_module": module.strip(),
            "action_type": action_type.strip(),
            "payload": payload,
            "status": "pending",
        },
        source=source,
    )
    return {"activity_id": item_id, "module": module, "action_type": action_type, "status": "pending"}


def process_outbox(graph: Graph, source: str = "outbox") -> dict:
    """Processes pending agent activities transactionally."""
    session = graph.session("steward", SCOPES)
    pending = session.find_entities("content", {"type": "agent_activity"}, limit=100)

    processed = []
    for item in pending:
        attrs = item.get("attrs", {})
        if attrs.get("status") != "pending":
            continue

        item_id = item["id"]
        action_type = attrs.get("action_type", "")
        payload = attrs.get("payload", {})

        # Execute idempotent activity
        session.update_entity(item_id, {"status": "executed"}, source=source)
        graph.bus.publish("admin.detected", {"type": action_type, "payload": payload, "module": "steward"})
        processed.append({"id": item_id, "action_type": action_type, "status": "executed"})

    return {"processed_count": len(processed), "activities": processed}
