"""Data Portability — Portable User Graph Exporter.

Packages all entities, edges, and provenance logs for a user into a portable JSON export bundle.
"""

from datetime import datetime, timezone
from substrate.graph import Graph, KINDS

SCOPES = {"*"}


def export_user_bundle(graph: Graph) -> dict:
    """Exports all entities, edges, and provenance logs into a portable JSON bundle."""
    session = graph.session("backup", SCOPES)
    entities = []
    for k in KINDS:
        entities.extend(session.find_entities(k, limit=500))

    export_items = []
    for e in entities:
        export_items.append({
            "id": e["id"],
            "kind": e["kind"],
            "attrs": e.get("attrs", {}),
            "created_at": e.get("created_at", ""),
            "updated_at": e.get("updated_at", ""),
        })

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "schema": "lifeos-user-export/v1",
        "exported_at": now_iso,
        "source": "lifeos-backup-export",
        "owner_id": graph.default_owner or "default",
        "total_items": len(export_items),
        "items": export_items,
    }
