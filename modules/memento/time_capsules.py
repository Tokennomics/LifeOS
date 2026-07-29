"""Memento — Time-Locked Memory Capsules.

Drop a memory capsule that unlocks on or after a specified future date.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"memories:read", "memories:write"}


def drop_time_capsule(graph: Graph, text: str, unlock_at: str, source: str = "memento") -> dict:
    """Drops a time-locked memory capsule."""
    if not text.strip():
        raise ValueError("a capsule needs some text")
    if not unlock_at.strip():
        raise ValueError("an unlock date is required")

    session = graph.session("memento", SCOPES)
    now_iso = datetime.now(timezone.utc).isoformat()

    attrs = {
        "type": "time_capsule",
        "text": text.strip(),
        "unlock_at": unlock_at.strip(),
        "locked": True,
        "dropped_at": now_iso,
    }
    capsule_id = session.create_entity("memory", attrs, source=source)
    graph.bus.publish("capsule.dropped", {"capsule_id": capsule_id, "type": "time_capsule", "module": "memento"})
    return {"capsule_id": capsule_id, "unlock_at": unlock_at.strip(), "locked": True}


def check_time_unlocks(graph: Graph, source: str = "memento") -> dict:
    """Unlocks all time-locked capsules whose unlock timestamp has passed."""
    session = graph.session("memento", SCOPES)
    now = datetime.now(timezone.utc)
    opened = []

    for capsule in session.find_entities("memory", {"type": "time_capsule"}, limit=200):
        attrs = capsule.get("attrs", {})
        if not attrs.get("locked", True):
            continue

        unlock_at_str = attrs.get("unlock_at", "")
        try:
            unlock_dt = datetime.fromisoformat(unlock_at_str.replace("Z", "+00:00"))
            if unlock_dt.tzinfo is None:
                unlock_dt = unlock_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        if now >= unlock_dt:
            session.update_entity(capsule["id"], {"locked": False}, source=source)
            graph.bus.publish("capsule.unlocked", {"capsule_id": capsule["id"], "type": "time_capsule", "module": "memento"})
            opened.append({
                "id": capsule["id"],
                "text": attrs.get("text", ""),
                "unlock_at": unlock_at_str,
            })

    return {"unlocked_count": len(opened), "opened": opened}
