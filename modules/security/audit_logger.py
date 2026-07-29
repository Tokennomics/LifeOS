"""System Audit Logger & Security Event Monitor.

Logs sensitive operations (grants, account changes, data exports)
for security, auditability, and compliance.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write"}
MODULE = "security"


def log_security_event(graph: Graph, event_type: str, actor_id: str = "system",
                       details: dict | None = None, source: str = MODULE) -> dict:
    """Logs a security audit event to the graph."""
    if not event_type.strip():
        raise ValueError("event_type required")

    now_iso = datetime.now(timezone.utc).isoformat()
    session = graph.session(MODULE, SCOPES)
    log_id = session.create_entity(
        "admin_item",
        {
            "type": "audit_log",
            "event_type": event_type.strip(),
            "actor_id": actor_id,
            "details": details or {},
            "timestamp": now_iso,
        },
        source=source,
    )
    return {"audit_id": log_id, "event_type": event_type, "timestamp": now_iso}


def get_security_audit_log(graph: Graph, limit: int = 100) -> list[dict]:
    """Retrieves recent security audit log events."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("admin_item", {"type": "audit_log"}, limit=limit)

    res = []
    for item in items:
        attrs = item.get("attrs", {})
        res.append({
            "audit_id": item["id"],
            "event_type": attrs.get("event_type", ""),
            "actor_id": attrs.get("actor_id", "system"),
            "details": attrs.get("details", {}),
            "timestamp": attrs.get("timestamp", ""),
        })

    return res
