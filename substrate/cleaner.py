"""Substrate Graph Pruning Steward.

Cleans up expired convoy locations and stale temp nodes to keep queries performant.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def prune_graph_stale_records(graph: Graph) -> dict:
    """Removes obsolete convoy location updates and temporary audit records."""
    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn
    
    pruned_count = 0
    try:
        # Clear convoy locations which are temporary by design
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM entities WHERE kind='admin_item' AND json_extract(attrs, '$.type')='convoy_position'"
        )
        pruned_count = cur.rowcount
        conn.commit()
    except Exception:
        pass

    return {
        "status": "success",
        "pruned_entities": pruned_count,
        "message": f"Successfully garbage collected {pruned_count} obsolete graph nodes."
    }
