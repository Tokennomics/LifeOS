"""Substrate Graph Backup & Restore Steward.

Handles database backup exports and restores as portable JSON structures.
"""

import json
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def export_backup(graph: Graph) -> dict:
    """Exports all entities and edges in the graph as a dictionary."""
    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn
    cur = conn.cursor()

    cur.execute("SELECT id, kind, attrs, owner_id, created_at, updated_at FROM entities")
    entities_rows = cur.fetchall()

    cur.execute("SELECT id, src, dst, rel, created_at FROM edges")
    edges_rows = cur.fetchall()

    entities = []
    for row in entities_rows:
        entities.append({
            "id": row[0],
            "kind": row[1],
            "attrs": json.loads(row[2]),
            "owner_id": row[3],
            "created_at": row[4],
            "updated_at": row[5]
        })

    edges = []
    for row in edges_rows:
        edges.append({
            "id": row[0],
            "src": row[1],
            "dst": row[2],
            "rel": row[3],
            "created_at": row[4]
        })

    return {
        "entities": entities,
        "edges": edges
    }


def import_restore(graph: Graph, backup_data: dict) -> bool:
    """Wipes and restores the graph database from backup data."""
    session = graph.session(MODULE, SCOPES)
    conn = session.graph.conn

    try:
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM observations")
        conn.execute("DELETE FROM entities")
        conn.commit()

        # Insert entities
        for ent in backup_data.get("entities", []):
            conn.execute(
                "INSERT INTO entities (id, kind, attrs, owner_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ent["id"], ent["kind"], json.dumps(ent["attrs"]), ent["owner_id"], ent["created_at"], ent["updated_at"])
            )
            # Also log standard baseline observations to satisfy DB integrity rules
            conn.execute(
                "INSERT INTO observations (id, entity_id, module, confidence, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ent["id"], ent["id"], "backup", 1.0, "restore", ent["created_at"])
            )

        # Insert edges
        for edge in backup_data.get("edges", []):
            conn.execute(
                "INSERT INTO edges (id, src, dst, rel, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (edge["id"], edge["src"], edge["dst"], edge["rel"], edge["created_at"])
            )

        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
