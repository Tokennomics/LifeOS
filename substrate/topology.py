"""Graph Network Topology Exporter.

Computes node degree distributions, centrality metrics, and exports standard JSON graph
topology for visualization.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "topology"


def export_graph_topology(graph: Graph) -> dict:
    """Computes node degree centrality and returns JSON network topology."""
    session = graph.session(MODULE, SCOPES)
    
    kinds = ["admin_item", "content", "decision", "event", "goal", "interest", "memory", "metric", "person", "place", "task"]
    entities = []
    for k in kinds:
        try:
            entities.extend(session.find_entities(k, limit=1000))
        except Exception:
            pass
    
    nodes = []
    node_degrees = {}
    
    # Pre-populate degree map
    for entity in entities:
        node_degrees[entity["id"]] = 0

    # Build standard entities list
    for entity in entities:
        attrs = entity.get("attrs", {})
        label = attrs.get("name") or attrs.get("title") or entity["kind"]
        nodes.append({
            "id": entity["id"],
            "kind": entity["kind"],
            "label": label,
            "degree": 0
        })

    # Gather edges
    links = []
    # Query edges via raw connection since substrate doesn't have a simple list_edges
    conn = session.graph.conn
    cur = conn.cursor()
    cur.execute("SELECT id, src, dst, rel FROM edges")
    edges = cur.fetchall()

    for edge_id, src, dst, rel in edges:
        if src in node_degrees and dst in node_degrees:
            node_degrees[src] += 1
            node_degrees[dst] += 1
            links.append({
                "id": edge_id,
                "source": src,
                "target": dst,
                "type": rel,
                "provenance": "substrate"
            })

    # Map computed degrees back to nodes list
    for node in nodes:
        node["degree"] = node_degrees.get(node["id"], 0)

    return {
        "nodes": nodes,
        "links": links
    }
