"""Substrate Graph Topology Hub Finder.

Identifies the highest-connectivity node hubs in the network.
"""

from collections import Counter
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def find_topology_hubs(graph: Graph) -> list[dict]:
    """Ranks all graph entities by degree centrality (connection density)."""
    session = graph.session(MODULE, SCOPES)
    
    # Query database directly for edge source and destination distribution
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

    # Fetch entity information for name resolution
    hubs = []
    for node_id, count in node_counts.most_common(100):
        # Resolve entity kind
        cur.execute("SELECT kind, attrs FROM entities WHERE id = ?", (node_id,))
        row = cur.fetchone()
        if row:
            kind, attrs_json = row
            try:
                import json
                attrs = json.loads(attrs_json)
            except Exception:
                attrs = {}
            name = attrs.get("name") or attrs.get("title") or attrs.get("body") or "Unnamed Node"
            hubs.append({
                "entity_id": node_id,
                "kind": kind,
                "name": name,
                "connections_count": count
            })

    return hubs
