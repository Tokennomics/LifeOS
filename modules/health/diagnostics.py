"""System Health — Graph Integrity & Diagnostics Scanner.

Automated health scanner verifying graph entity integrity, edge references,
and database consistency.
"""

from substrate.graph import Graph, KINDS

SCOPES = {"*"}


def run_diagnostics(graph: Graph) -> dict:
    """Runs automated health check on the graph database."""
    session = graph.session("health", SCOPES)

    all_entities = []
    entities_by_kind = {}
    for k in KINDS:
        e_list = session.find_entities(k, limit=5000)
        entities_by_kind[k] = len(e_list)
        all_entities.extend(e_list)

    entity_ids = {e["id"] for e in all_entities}
    issues = []

    # Verify edge integrity using raw query if needed
    orphaned_edges = []
    total_edges = 0

    cur = graph.conn.cursor()
    cur.execute("SELECT id, src, dst, rel FROM edges")
    edges_rows = cur.fetchall()
    total_edges = len(edges_rows)

    for row in edges_rows:
        eid, src, dst, rel = row[0], row[1], row[2], row[3]
        if src not in entity_ids or dst not in entity_ids:
            orphaned_edges.append({"edge_id": eid, "src_id": src, "dst_id": dst, "rel": rel})

    if orphaned_edges:
        issues.append(f"Found {len(orphaned_edges)} orphaned edges pointing to deleted or missing entities.")

    healthy = len(issues) == 0

    return {
        "healthy": healthy,
        "total_entities": len(all_entities),
        "entities_by_kind": entities_by_kind,
        "total_edges": total_edges,
        "orphaned_edges": orphaned_edges,
        "issues": issues,
    }
