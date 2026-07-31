"""Advanced Graph Centrality Analytics.

Computes degree centrality scores to rank critical hub entities.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def calculate_centrality(graph: Graph) -> list[dict]:
    """Calculates node degree centrality rankings across all entity kinds."""
    session = graph.session(MODULE, SCOPES)
    
    kinds = ["admin_item", "content", "decision", "event", "goal", "interest", "memory", "metric", "person", "place", "task"]
    entities = []
    for k in kinds:
        try:
            entities.extend(session.find_entities(k, limit=1000))
        except Exception:
            pass

    degrees = {ent["id"]: 0 for ent in entities}
    entities_by_id = {ent["id"]: ent for ent in entities}

    # Query edges
    conn = session.graph.conn
    cur = conn.cursor()
    cur.execute("SELECT src, dst FROM edges")
    edges = cur.fetchall()

    for src, dst in edges:
        if src in degrees:
            degrees[src] += 1
        if dst in degrees:
            degrees[dst] += 1

    rankings = []
    for ent_id, score in degrees.items():
        ent = entities_by_id[ent_id]
        attrs = ent.get("attrs", {})
        label = attrs.get("name") or attrs.get("title") or ent["kind"]
        rankings.append({
            "entity_id": ent_id,
            "kind": ent["kind"],
            "label": label,
            "centrality_score": score
        })

    # Sort descending
    rankings.sort(key=lambda x: x["centrality_score"], reverse=True)
    return rankings
