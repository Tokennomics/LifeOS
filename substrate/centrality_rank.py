"""Graph Node Centrality Density Ranker.

Ranks entity nodes by centrality ratios to highlight focal points in the network.
"""

from collections import Counter
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def rank_nodes_centrality(graph: Graph) -> list[dict]:
    """Calculates density centrality ratios (degree centrality) for all nodes."""
    session = graph.session(MODULE, SCOPES)
    
    conn = session.graph.conn
    cur = conn.cursor()
    cur.execute("SELECT src, dst FROM edges")
    edges = cur.fetchall()

    if not edges:
        return []

    node_counts = Counter()
    for src, dst in edges:
        node_counts[src] += 1
        node_counts[dst] += 1

    total_edges = len(edges)
    hubs = []
    
    for node_id, count in node_counts.most_common(100):
        cur.execute("SELECT kind, attrs FROM entities WHERE id = ?", (node_id,))
        row = cur.fetchone()
        if row:
            kind, attrs_json = row
            try:
                import json
                attrs = json.loads(attrs_json)
            except Exception:
                attrs = {}
            name = attrs.get("name") or attrs.get("title") or "Unnamed Node"
            
            # Centrality ratio: connections divided by total possible connections
            ratio = count / (2 * total_edges) if total_edges > 0 else 0.0
            
            hubs.append({
                "entity_id": node_id,
                "kind": kind,
                "name": name,
                "connections": count,
                "centrality_ratio": round(ratio, 4)
            })

    return hubs
