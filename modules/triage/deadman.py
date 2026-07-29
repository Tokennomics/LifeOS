"""Triage OS — Best-Effort Dead-Man's Switch.

Manual peace-of-mind check-in monitor that alerts private contacts if un-checked-in
past a configured grace period.

DISCLAIMER: Best-effort software only. Never connects to emergency services (112/911).
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"content:read", "content:write"}


def set_config(graph: Graph, interval_hours: float = 24.0, grace_hours: float = 12.0,
               contacts: list[dict] | None = None, source: str = "triage") -> dict:
    """Configures the dead-man's switch settings."""
    session = graph.session("triage", SCOPES)
    existing = session.find_entities("content", {"type": "deadman_config"}, limit=1)

    now_iso = datetime.now(timezone.utc).isoformat()
    attrs = {
        "type": "deadman_config",
        "interval_hours": max(1.0, float(interval_hours)),
        "grace_hours": max(1.0, float(grace_hours)),
        "contacts": contacts or [],
        "last_ping": now_iso,
        "enabled": True,
    }

    if existing:
        cid = existing[0]["id"]
        # Keep previous last_ping if exists
        attrs["last_ping"] = existing[0].get("attrs", {}).get("last_ping", now_iso)
        session.update_entity(cid, attrs, source=source)
    else:
        cid = session.create_entity("content", attrs, source=source)

    attrs["id"] = cid
    return attrs


def ping(graph: Graph, source: str = "triage") -> dict:
    """Records a user check-in ping."""
    session = graph.session("triage", SCOPES)
    existing = session.find_entities("content", {"type": "deadman_config"}, limit=1)
    now_iso = datetime.now(timezone.utc).isoformat()

    if not existing:
        # Create default config on first ping
        cid = session.create_entity(
            "content",
            {"type": "deadman_config", "interval_hours": 24.0, "grace_hours": 12.0, "contacts": [], "last_ping": now_iso, "enabled": True},
            source=source,
        )
    else:
        cid = existing[0]["id"]
        session.update_entity(cid, {"last_ping": now_iso}, source=source)

    return {"status": "ok", "last_ping": now_iso}


def check_status(graph: Graph) -> dict:
    """Checks check-in freshness and returns status and alert drafts if overdue."""
    session = graph.session("triage", SCOPES)
    existing = session.find_entities("content", {"type": "deadman_config"}, limit=1)
    if not existing:
        return {"configured": False, "status": "disabled", "hours_elapsed": 0.0}

    attrs = existing[0].get("attrs", {})
    if not attrs.get("enabled", True):
        return {"configured": True, "status": "disabled", "hours_elapsed": 0.0}

    last_ping_str = attrs.get("last_ping", "")
    interval_h = attrs.get("interval_hours", 24.0)
    grace_h = attrs.get("grace_hours", 12.0)
    contacts = attrs.get("contacts", [])

    now = datetime.now(timezone.utc)
    try:
        ping_dt = datetime.fromisoformat(last_ping_str.replace("Z", "+00:00"))
        if ping_dt.tzinfo is None:
            ping_dt = ping_dt.replace(tzinfo=timezone.utc)
        hours_elapsed = (now - ping_dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        hours_elapsed = 0.0

    if hours_elapsed <= interval_h:
        state = "ok"
    elif hours_elapsed <= interval_h + grace_h:
        state = "warning"
    else:
        state = "overdue"

    draft_alerts = []
    if state == "overdue":
        for c in contacts:
            draft_alerts.append({
                "contact_name": c.get("name", "Contact"),
                "contact_target": c.get("target", ""),
                "message": f"Peace-of-mind alert: Check-in was missed ({hours_elapsed:.1f} hours since last ping). Please reach out to verify well-being.",
            })

    return {
        "configured": True,
        "status": state,
        "hours_elapsed": round(hours_elapsed, 1),
        "interval_hours": interval_h,
        "grace_hours": grace_h,
        "last_ping": last_ping_str,
        "draft_alerts": draft_alerts,
    }
