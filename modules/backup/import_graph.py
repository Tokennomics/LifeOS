"""Data Portability — Portable User Graph Restoration Engine.

Import & restoration engine for portable lifeos-user-export/v1 JSON backup archives.
"""

from substrate.graph import Graph, KINDS

SCOPES = {"*"}
MODULE = "backup"


def restore_user_bundle(graph: Graph, bundle_data: dict, source: str = MODULE) -> dict:
    """Restores user entities from a portable JSON backup bundle."""
    if not isinstance(bundle_data, dict):
        raise ValueError("bundle_data must be a dict")

    schema = bundle_data.get("schema")
    if schema != "lifeos-user-export/v1":
        raise ValueError(f"unsupported backup schema: {schema!r}")

    entities = bundle_data.get("entities", [])
    session = graph.session(MODULE, SCOPES)

    restored_count = 0
    for item in entities:
        kind = item.get("kind")
        attrs = item.get("attrs", {})
        if kind in KINDS and attrs:
            session.create_entity(kind, attrs, source=source)
            restored_count += 1

    return {
        "status": "restored",
        "schema": schema,
        "restored_entities_count": restored_count,
    }
