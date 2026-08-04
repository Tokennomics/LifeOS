"""Social Clique Cluster Detector.

Groups users into social cliques/clusters based on common co-attendance in outings.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def detect_social_cliques(graph: Graph) -> list[list[str]]:
    """Groups people nodes into cohesive clusters based on mutual connection density."""
    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn
    cur = conn.cursor()

    # Query all 'with' edges to map connections
    cur.execute("SELECT src, dst FROM edges WHERE rel='with'")
    edges = cur.fetchall()

    adj = {}
    for src, dst in edges:
        adj.setdefault(src, set()).add(dst)
        adj.setdefault(dst, set()).add(src)

    # Simple connected components algorithm to find clusters
    visited = set()
    cliques = []

    for node in adj:
        if node not in visited:
            comp = []
            queue = [node]
            visited.add(node)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for neighbor in adj.get(curr, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            cliques.append(sorted(comp))

    return cliques
