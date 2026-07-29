"""Structured System Logger & Telemetry Engine.

Production JSON structured logging, performance metrics, and exception tracebacks.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write"}
MODULE = "telemetry"


def log_system_event(graph: Graph, level: str, module_name: str, message: str,
                     metadata: dict | None = None, source: str = MODULE) -> dict:
    """Logs a structured system event to the graph."""
    lvl_clean = level.upper().strip()
    if not message.strip():
        raise ValueError("message required")

    now_iso = datetime.now(timezone.utc).isoformat()
    session = graph.session(MODULE, SCOPES)
    log_id = session.create_entity(
        "admin_item",
        {
            "type": "system_log",
            "level": lvl_clean,
            "module": module_name.strip(),
            "message": message.strip(),
            "metadata": metadata or {},
            "timestamp": now_iso,
        },
        source=source,
    )
    return {"log_id": log_id, "level": lvl_clean, "timestamp": now_iso}


def get_system_logs(graph: Graph, level: str | None = None, limit: int = 100) -> list[dict]:
    """Retrieves system logs filtered by log level."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("admin_item", {"type": "system_log"}, limit=limit)

    lvl_filter = level.upper().strip() if level else None

    res = []
    for item in items:
        attrs = item.get("attrs", {})
        l_level = attrs.get("level", "INFO")
        if lvl_filter and l_level != lvl_filter:
            continue
        res.append({
            "log_id": item["id"],
            "level": l_level,
            "module": attrs.get("module", ""),
            "message": attrs.get("message", ""),
            "metadata": attrs.get("metadata", {}),
            "timestamp": attrs.get("timestamp", ""),
        })

    return res
