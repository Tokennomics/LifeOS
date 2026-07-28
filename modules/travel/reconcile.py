"""Travel Mode reconciliation logic (T2).

Parses a Travel Mode export bundle, skips already-imported entities and edges,
and inserts the rest preserving their stable IDs and original timestamps.
"""

from substrate.graph import Graph, GraphError


def reconcile(graph: Graph, bundle: dict) -> dict:
    if bundle.get("schema") != "lifeos-travel-export/v1":
        raise ValueError(f"Unsupported bundle schema: {bundle.get('schema')}")

    session = graph.session("travel", {"*"})
    items = bundle.get("items", [])

    entities = [item for item in items if item.get("type") == "entity"]
    edges = [item for item in items if item.get("type") == "edge"]

    entities_imported = 0
    edges_imported = 0
    skipped = 0

    # Pass 1: Ingest entities
    for item in entities:
        key = item.get("key")
        if not key:
            raise ValueError("Entity item is missing stable 'key'")
        
        # Check if entity already exists
        existing = session.get_entity(key)
        if existing is not None:
            skipped += 1
            continue

        session.create_entity(
            kind=item["kind"],
            attrs=item.get("attrs", {}),
            source="travel_import",
            confidence=1.0,
            entity_id=key,
            created_at=item.get("ts"),
        )
        entities_imported += 1

    # Pass 2: Ingest edges
    g = session.graph
    for item in edges:
        key = item.get("key")
        if not key:
            raise ValueError("Edge item is missing stable 'key'")

        # Check if edge already exists
        cur = g._execute(f"SELECT 1 FROM edges WHERE id = {g.ph}", (key,))
        existing = cur.fetchone()
        if existing is not None:
            skipped += 1
            continue

        try:
            session.create_edge(
                src=item["src"],
                dst=item["dst"],
                rel=item["rel"],
                attrs=item.get("attrs", {}),
                source="travel_import",
                confidence=1.0,
                edge_id=key,
                created_at=item.get("ts"),
            )
            edges_imported += 1
        except GraphError as exc:
            # If endpoints don't exist, we skip or raise. Raise is safer for contract parity.
            raise ValueError(f"Failed to import edge {key}: {exc}")

    return {
        "entities_imported": entities_imported,
        "edges_imported": edges_imported,
        "skipped": skipped,
    }
