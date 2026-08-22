"""Personal graph backup and restore.

**Both functions are the caller's own slice only, and that is the entire point of this
file.** The first version read and wrote raw SQL against the whole database with no owner
predicate anywhere, which made `POST /v1/graph/restore` — an ordinary authenticated
endpoint, no operator gate — into this:

    DELETE FROM edges; DELETE FROM observations; DELETE FROM entities;

...for every owner on the box, triggered by any signed-in user posting `{}`. It was
demonstrated before it was fixed: a second account posted an empty body and the first
account's graph went to zero and she could no longer log in, because accounts are entities
too. `export_backup` was the same hole pointed the other way — a complete dump of every
other user's people, goals and memories to anyone with a login.

So restore now goes through `substrate/graph.py` like every other write in the system,
rather than around it. That is not tidiness: the session API is where owner scoping,
kind validation and provenance live, and this module reimplemented all three badly by
talking to the connection directly. Going through it means a restore cannot name someone
else's `owner_id`, cannot invent a kind, and leaves an observation trail like everything
else.
"""

from substrate.graph import KINDS, RELS, SCOPE_DOMAIN, Graph

SCOPES = {"*"}
MODULE = "substrate"

#: A cap so one restore cannot be used to fill the disk. Generous for a personal graph.
MAX_ENTITIES = 20_000
MAX_EDGES = 40_000


def _session(graph: Graph):
    return graph.session(MODULE, SCOPES)


def export_backup(graph: Graph) -> dict:
    """Everything the caller owns, as portable JSON. Never anyone else's."""
    session = _session(graph)

    entities = []
    for kind in sorted(KINDS):
        for row in session.find_entities(kind, limit=MAX_ENTITIES):
            entities.append({
                "id": row["id"], "kind": kind, "attrs": row.get("attrs") or {},
                "owner_id": row.get("owner_id", ""),
                "created_at": row.get("created_at", ""),
                "updated_at": row.get("updated_at", ""),
            })

    owned = {entity["id"] for entity in entities}
    edges = []
    if owned:
        g = session.graph
        cur = g.conn.cursor()
        cur.execute("SELECT id, src, dst, rel, created_at FROM edges")
        for row in cur.fetchall():
            # An edge belongs to you if either end does — the same rule /v1/export uses.
            if row[1] in owned or row[2] in owned:
                edges.append({"id": row[0], "src": row[1], "dst": row[2],
                              "rel": row[3], "created_at": row[4]})

    return {"entities": entities, "edges": edges}


def import_restore(graph: Graph, backup_data: dict, *, source: str = MODULE) -> dict:
    """Replace the caller's own graph with the contents of a backup.

    Destructive, deliberately — it is a restore. But only ever to the caller's own slice:
    the incoming `owner_id` on each row is ignored and replaced with the caller's, so a
    crafted backup cannot write into anybody else's graph or delete from it.
    """
    if not isinstance(backup_data, dict):
        raise ValueError("a restore needs a backup object")

    entities = backup_data.get("entities")
    edges = backup_data.get("edges") or []
    if not isinstance(entities, list) or not isinstance(edges, list):
        raise ValueError("a backup needs 'entities' and 'edges' lists")
    if not entities:
        # The empty-body wipe, refused by name. A restore that deletes everything and puts
        # nothing back is indistinguishable from an accident, and it was reachable by
        # posting `{}` to an endpoint any user can call.
        raise ValueError(
            "a restore needs at least one entity — refusing to wipe the graph and put "
            "nothing back. Take a backup first with POST /v1/graph/backup.")
    if len(entities) > MAX_ENTITIES or len(edges) > MAX_EDGES:
        raise ValueError(f"a backup is capped at {MAX_ENTITIES} entities "
                         f"and {MAX_EDGES} edges")

    session = _session(graph)
    owner = session.graph.default_owner

    # Clear the caller's slice. `delete_entity` is owner-scoped and takes the entity's
    # edges and observations with it, so an id outside this slice simply is not found.
    removed = 0
    for kind in sorted(KINDS):
        for row in session.find_entities(kind, limit=MAX_ENTITIES):
            session.delete_entity(row["id"], source=source)
            removed += 1

    g = session.graph

    def _taken(entity_id: str) -> bool:
        """Does this id already exist anywhere? After the wipe above, a surviving id
        necessarily belongs to another owner — restoring onto it would either collide or,
        worse, be a way to aim at somebody else's row."""
        if not entity_id:
            return False
        cur = g.conn.cursor()
        cur.execute(f"SELECT 1 FROM entities WHERE id = {g.ph}", (entity_id,))
        return cur.fetchone() is not None

    restored, skipped = 0, 0
    id_map: dict[str, str] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            skipped += 1
            continue
        kind = str(entity.get("kind") or "")
        attrs = entity.get("attrs")
        if kind not in KINDS or not isinstance(attrs, dict):
            skipped += 1
            continue
        old_id = str(entity.get("id") or "")
        # Keep the original id where it is free, so a restore of your own backup is exact
        # and repeatable. Where it is taken, mint a fresh one rather than failing the whole
        # restore — importing someone else's export is a legitimate thing to do, and it must
        # not become a way to write onto their rows.
        wanted = None if _taken(old_id) else (old_id or None)
        new_id = session.create_entity(
            kind, attrs, source=source,
            owner_id=owner,                       # never the value in the file
            entity_id=wanted,
            created_at=str(entity.get("created_at") or "") or None,
            updated_at=str(entity.get("updated_at") or "") or None)
        if old_id:
            id_map[old_id] = new_id
        restored += 1

    edges_restored = 0
    for edge in edges:
        if not isinstance(edge, dict):
            skipped += 1
            continue
        src = id_map.get(str(edge.get("src") or ""))
        dst = id_map.get(str(edge.get("dst") or ""))
        rel = str(edge.get("rel") or "")
        # Both ends have to be entities this restore just created. Anything else is either a
        # dangling reference or an attempt to attach to somebody else's entity.
        if rel not in RELS or not src or not dst:
            skipped += 1
            continue
        session.create_edge(src, dst, rel, source=source,
                            created_at=str(edge.get("created_at") or "") or None)
        edges_restored += 1

    return {"restored": True, "entities": restored, "edges": edges_restored,
            "removed": removed, "skipped": skipped}
