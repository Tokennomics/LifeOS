"""Substrate Graph Topology Hub Finder.

Identifies the highest-connectivity node hubs in the network.
"""

import json
from collections import Counter

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def find_topology_hubs(graph: Graph) -> list[dict]:
    """Rank the caller's own entities by degree centrality (connection density).

    **Owner-scoped, and that is the whole subtlety here.** `edges` carries no `owner_id` —
    the v0 schema is final, so the boundary has to be reconstructed by joining back to
    `entities`. The first version of this function did `SELECT src, dst FROM edges` with no
    join at all and then resolved every node's `name`/`title` straight out of the table,
    which on a shared box is every other user's people, goals and memories by name.

    It was never reachable: the endpoint called `export_graph_topology`, which does not
    exist, so it had always returned a 500. That is the trap — the obvious "fix" is to
    correct the function name, and correcting the function name is what would have shipped
    the leak. The scoping is the fix; the rename is incidental.
    """
    session = graph.session(MODULE, SCOPES)
    g = session.graph
    owner = g.default_owner
    conn = g.conn
    cur = conn.cursor()

    owned = f"SELECT id FROM entities WHERE owner_id = {g.ph}"
    if owner:
        # An edge counts if either end is yours; a node only counts if it is yours.
        cur.execute(f"SELECT src, dst FROM edges WHERE src IN ({owned}) OR dst IN ({owned})",
                    (owner, owner))
    else:
        # No owner scope is the single-user config-owner install: there is only one owner.
        cur.execute("SELECT src, dst FROM edges")
    edges = cur.fetchall()
    if not edges:
        return []

    node_counts = Counter()
    for src, dst in edges:
        node_counts[src] += 1
        node_counts[dst] += 1

    hubs = []
    for node_id, count in node_counts.most_common(100):
        if owner:
            cur.execute(
                f"SELECT kind, attrs FROM entities WHERE id = {g.ph} AND owner_id = {g.ph}",
                (node_id, owner))
        else:
            cur.execute(f"SELECT kind, attrs FROM entities WHERE id = {g.ph}", (node_id,))
        row = cur.fetchone()
        if not row:
            continue            # the far end of an edge into someone else's slice
        kind, attrs_json = row[0], row[1]
        try:
            attrs = json.loads(attrs_json) if isinstance(attrs_json, str) else (attrs_json or {})
        except (TypeError, ValueError):
            attrs = {}
        hubs.append({
            "entity_id": node_id,
            "kind": kind,
            "name": attrs.get("name") or attrs.get("title") or attrs.get("body")
            or "Unnamed Node",
            "connections_count": count,
        })

    return hubs
