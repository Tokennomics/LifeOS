"""Knowledge Graph Integrity Check Steward.

Audits knowledge base integrity for dangling references or broken edge pointers.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def audit_graph_integrity(graph: Graph) -> dict:
    """Verifies that all edge relationships connect valid existing entities."""
    session = graph.session(MODULE, SCOPES)
    
    kinds = ["admin_item", "content", "decision", "event", "goal", "interest", "memory", "metric", "person", "place", "task"]
    entity_ids = set()
    for k in kinds:
        try:
            for ent in session.find_entities(k, limit=1000):
                entity_ids.add(ent["id"])
        except Exception:
            pass

    conn = session.graph.conn
    cur = conn.cursor()
    cur.execute("SELECT id, src, dst, rel FROM edges")
    edges = cur.fetchall()

    broken_edges = []
    for edge_id, src, dst, rel in edges:
        src_ok = src in entity_ids
        dst_ok = dst in entity_ids
        if not src_ok or not dst_ok:
            broken_edges.append({
                "edge_id": edge_id,
                "src": src,
                "dst": dst,
                "rel": rel,
                "src_missing": not src_ok,
                "dst_missing": not dst_ok
            })

    total_edges = len(edges)
    healthy_edges = total_edges - len(broken_edges)
    health_ratio = healthy_edges / total_edges if total_edges > 0 else 1.0

    return {
        "integrity_score": round(health_ratio * 100, 1),
        "total_edges": total_edges,
        "broken_edges_count": len(broken_edges),
        "broken_edges": broken_edges,
        "status": "Healthy" if health_ratio >= 0.95 else "Intervention Recommended"
    }
