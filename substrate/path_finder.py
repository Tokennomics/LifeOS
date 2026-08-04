"""Graph Social Connection Path-Finder.

Computes connection pathways between nodes inside the Substrate Graph.
"""

from collections import deque
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def find_social_paths(graph: Graph, src_id: str, dst_id: str) -> list[str]:
    """Computes the shortest connection path between two arbitrary graph entities."""
    if not src_id.strip() or not dst_id.strip():
        raise ValueError("src_id and dst_id are required")

    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn
    cur = conn.cursor()

    # Load whole adjacency list in memory for fast local pathfinding
    cur.execute("SELECT src, dst FROM edges")
    edges = cur.fetchall()

    adj = {}
    for src, dst in edges:
        adj.setdefault(src, set()).add(dst)
        adj.setdefault(dst, set()).add(src)

    if src_id not in adj or dst_id not in adj:
        return []

    # Standard BFS to find shortest path
    queue = deque([[src_id]])
    visited = {src_id}

    while queue:
        path = queue.popleft()
        node = path[-1]

        if node == dst_id:
            return path

        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])

    return []
