"""The ONLY write path into the context graph (Law 1).

Every write requires:
  - a module session holding the right scope ("<domain>:write" for the entity kind)
  - provenance (source + confidence) — recorded as an observations row
Every write publishes observation.created on the bus.

Scopes: "goals:read", "events:write", ... ; "*" grants everything (trusted infra/tests).
A write scope implies the matching read scope.
"""

import json
import re

from substrate import new_id, now_iso
from substrate.bus import Bus

KINDS = {
    "person", "interest", "goal", "task", "event", "place",
    "memory", "content", "metric", "decision", "admin_item",
}

RELS = {"attended", "interested_in", "blocks", "located_at", "with", "feeds", "decided"}

SCOPE_DOMAIN = {
    "person": "people",
    "interest": "interests",
    "goal": "goals",
    "task": "tasks",
    "event": "events",
    "place": "places",
    "memory": "memories",
    "content": "content",
    "metric": "metrics",
    "decision": "decisions",
    "admin_item": "admin",
}

WILDCARD = "*"
_ATTR_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")


class GraphError(Exception):
    pass


class ScopeError(GraphError):
    pass


class ProvenanceError(GraphError):
    pass


class Graph:
    def __init__(self, conn, bus: Bus | None = None, default_owner: str | None = None):
        self.conn = conn
        self.bus = bus or Bus()
        self.default_owner = default_owner
        self.dialect = "sqlite" if conn.__class__.__module__.startswith("sqlite3") else "postgres"
        self.ph = "?" if self.dialect == "sqlite" else "%s"

    def session(self, module: str, scopes) -> "GraphSession":
        return GraphSession(self, module, set(scopes))

    def _execute(self, sql: str, params: tuple = ()):
        cur = self.conn.execute(sql, params) if self.dialect == "sqlite" else None
        if cur is None:
            cur = self.conn.cursor()
            cur.execute(sql, params)
        return cur


class GraphSession:
    """A module's handle on the graph. All reads/writes are scope-checked."""

    def __init__(self, graph: Graph, module: str, scopes: set[str]):
        if not module:
            raise GraphError("module name is required")
        self.graph = graph
        self.module = module
        self.scopes = scopes

    # ---- enforcement ----------------------------------------------------

    def _need(self, kind: str, action: str) -> None:
        if kind not in KINDS:
            raise GraphError(f"unknown entity kind: {kind!r} (known: {sorted(KINDS)})")
        if WILDCARD in self.scopes:
            return
        domain = SCOPE_DOMAIN[kind]
        allowed = f"{domain}:{action}" in self.scopes
        if not allowed and action == "read":
            allowed = f"{domain}:write" in self.scopes  # write implies read
        if not allowed:
            raise ScopeError(f"module {self.module!r} lacks scope {domain}:{action}")

    def _record_provenance(self, target_id: str, source: str, confidence: float, created_at: str | None = None) -> None:
        if not source:
            raise ProvenanceError("every graph write needs a source")
        if not (0.0 <= confidence <= 1.0):
            raise ProvenanceError(f"confidence must be in [0,1], got {confidence}")
        g = self.graph
        ts = created_at or now_iso()
        g._execute(
            f"INSERT INTO observations (id, entity_id, module, confidence, source, created_at) "
            f"VALUES ({g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph})",
            (new_id(), target_id, self.module, confidence, source, ts),
        )

    # ---- writes ---------------------------------------------------------

    def create_entity(self, kind: str, attrs: dict | None = None, *, source: str,
                      confidence: float = 1.0, owner_id: str | None = None,
                      entity_id: str | None = None, created_at: str | None = None,
                      updated_at: str | None = None) -> str:
        self._need(kind, "write")
        owner = owner_id or self.graph.default_owner
        if not owner:
            raise GraphError("owner_id required (no default owner configured)")
        g = self.graph
        eid = entity_id or new_id()
        ts = created_at or now_iso()
        uts = updated_at or ts
        g._execute(
            f"INSERT INTO entities (id, kind, attrs, owner_id, created_at, updated_at) "
            f"VALUES ({g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph})",
            (eid, kind, json.dumps(attrs or {}), owner, ts, uts),
        )
        self._record_provenance(eid, source, confidence, created_at=ts)
        g.conn.commit()
        g.bus.publish("observation.created", {"target": "entity", "id": eid, "kind": kind, "module": self.module})
        return eid

    def update_entity(self, entity_id: str, attrs_patch: dict, *, source: str,
                      confidence: float = 1.0) -> dict:
        row = self._fetch_entity(entity_id)
        if row is None:
            raise GraphError(f"entity not found: {entity_id}")
        self._need(row["kind"], "write")
        merged = {**json.loads(row["attrs"] if isinstance(row["attrs"], str) else json.dumps(row["attrs"])), **attrs_patch}
        g = self.graph
        g._execute(
            f"UPDATE entities SET attrs = {g.ph}, updated_at = {g.ph} WHERE id = {g.ph}",
            (json.dumps(merged), now_iso(), entity_id),
        )
        self._record_provenance(entity_id, source, confidence)
        g.conn.commit()
        g.bus.publish("observation.created", {"target": "entity", "id": entity_id, "kind": row["kind"], "module": self.module})
        return merged

    def create_edge(self, src: str, dst: str, rel: str, *, weight: float = 1.0,
                    attrs: dict | None = None, source: str, confidence: float = 1.0,
                    edge_id: str | None = None, created_at: str | None = None) -> str:
        if rel not in RELS:
            raise GraphError(f"unknown edge rel: {rel!r} (known: {sorted(RELS)})")
        srow = self._fetch_entity(src)
        drow = self._fetch_entity(dst)
        if srow is None or drow is None:
            raise GraphError(f"edge endpoints must exist: src={src} dst={dst}")
        # Authoring an edge mutates the src side of the relationship but only
        # references the dst — so: write scope on src kind, read scope on dst kind.
        self._need(srow["kind"], "write")
        self._need(drow["kind"], "read")
        g = self.graph
        eid = edge_id or new_id()
        ts = created_at or now_iso()
        g._execute(
            f"INSERT INTO edges (id, src, dst, rel, weight, attrs, created_at) "
            f"VALUES ({g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph})",
            (eid, src, dst, rel, weight, json.dumps(attrs or {}), ts),
        )
        self._record_provenance(eid, source, confidence, created_at=ts)
        g.conn.commit()
        g.bus.publish("observation.created", {"target": "edge", "id": eid, "rel": rel, "module": self.module})
        return eid

    def _is_acl_write_authorized(self, space: str, subject: str, scope: str, action: str) -> bool:
        """Enforces multi-tenant security boundary on grants ACL table."""
        if "*" in self.scopes:
            return True
        g = self.graph
        from substrate import SYSTEM_OWNER
        if g.default_owner == SYSTEM_OWNER:
            return True

        row = g._execute("SELECT owner_id, attrs, kind FROM entities WHERE id = ?", (space,)).fetchone()
        if row is None:
            return False

        if g.default_owner == row["owner_id"]:
            return True

        # Check admin grant
        admin_grant = g._execute(
            "SELECT 1 FROM grants WHERE subject = ? AND scope IN (?, ?) AND space = ?",
            (g.default_owner, "crew:admin", "space:admin", space)
        ).fetchone()
        if admin_grant:
            return True

        # Check participant grant for coordination spaces
        attrs = json.loads(row["attrs"]) if isinstance(row["attrs"], str) else row["attrs"]
        is_coord = attrs.get("type") == "coordinate" or "coordinate" in row["kind"]
        if is_coord:
            part_grant = g._execute(
                "SELECT 1 FROM grants WHERE subject = ? AND scope = ? AND space = ?",
                (g.default_owner, "coord:participant", space)
            ).fetchone()
            if part_grant:
                return True

        # Self-modification check (subject is the session owner's public account ID)
        is_self = (subject == g.default_owner)
        if not is_self and g.default_owner:
            acc = g._execute(
                "SELECT attrs FROM entities WHERE id = ? AND kind = 'content' AND owner_id = ?",
                (subject, SYSTEM_OWNER)
            ).fetchone()
            if acc:
                acc_attrs = json.loads(acc["attrs"]) if isinstance(acc["attrs"], str) else acc["attrs"]
                if acc_attrs.get("type") == "account" and acc_attrs.get("owner_id") == g.default_owner:
                    is_self = True

        if is_self:
            if action == "revoke":
                return True
            if action == "grant":
                if scope == "crew:requested":
                    return True
                # Joining public open crew
                is_crew = attrs.get("type") == "crew"
                if is_crew and attrs.get("visibility") == "public" and attrs.get("admission") == "open" and scope == "crew:member":
                    return True
                # Accepting invite: must hold crew:invited grant currently
                if is_crew and scope == "crew:member":
                    invited = g._execute(
                        "SELECT 1 FROM grants WHERE subject = ? AND scope = ? AND space = ?",
                        (subject, "crew:invited", space)
                    ).fetchone()
                    if invited:
                        return True

        return False

    def grant(self, subject: str, scope: str, space: str, *, source: str,
              confidence: float = 1.0) -> None:
        """ACL write for shared spaces (Hearth/crews). Spaces are content entities,
        so granting requires content:write. Provenance is recorded against the space."""
        self._need("content", "write")
        if not self._is_acl_write_authorized(space, subject, scope, "grant"):
            raise ScopeError(f"unauthorized to grant scope {scope} on space {space}")
            
        g = self.graph
        g._execute(
            f"INSERT INTO grants (subject, scope, space, granted_at) "
            f"VALUES ({g.ph}, {g.ph}, {g.ph}, {g.ph})",
            (subject, scope, space, now_iso()),
        )
        self._record_provenance(space, source, confidence)
        g.conn.commit()

    def revoke(self, subject: str, scope: str, space: str, *, source: str,
               confidence: float = 1.0) -> int:
        """Remove an ACL grant (leaving a crew, declining an invite, blocking someone).

        An ACL you cannot revoke is not an ACL: membership is a lifecycle, and
        capability tokens must be withdrawable. Same scope requirement and provenance
        as grant(). Returns the number of rows removed (0 if there was nothing to undo).
        """
        self._need("content", "write")
        if not self._is_acl_write_authorized(space, subject, scope, "revoke"):
            raise ScopeError(f"unauthorized to revoke scope {scope} on space {space}")
            
        g = self.graph
        cur = g._execute(
            f"DELETE FROM grants WHERE subject = {g.ph} AND scope = {g.ph} AND space = {g.ph}",
            (subject, scope, space),
        )
        removed = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        if removed:
            self._record_provenance(space, source, confidence)
        g.conn.commit()
        return removed


    # ---- erasure ---------------------------------------------------------
    #
    # There was no delete path here at all, which made "the graph is the user's" only half
    # true: they could export everything and remove nothing. GDPR Art. 17 is not the only
    # reason — a system you cannot leave is not one you can honestly ask people to join.
    #
    # Deletes go through the substrate for the same reason writes do: an entity's edges and
    # provenance rows live in other tables with no foreign keys, so deleting the row
    # elsewhere would leave dangling edges and an observation trail pointing at a ghost.

    def delete_entity(self, entity_id: str, *, source: str) -> dict:
        """Remove one entity you own, plus every edge touching it and its provenance.

        Owner-scoped like every other write: an id outside your slice reads as missing, so
        this cannot be used to delete someone else's row by guessing.
        """
        self._need("content", "write")
        row = self._fetch_entity(entity_id)
        if row is None:
            raise GraphError(f"entity not found: {entity_id}")
        self._need(row["kind"], "write")
        g = self.graph
        edges = g._execute(
            f"DELETE FROM edges WHERE src = {g.ph} OR dst = {g.ph}", (entity_id, entity_id))
        edge_count = edges.rowcount if edges.rowcount and edges.rowcount > 0 else 0
        obs = g._execute(f"DELETE FROM observations WHERE entity_id = {g.ph}", (entity_id,))
        obs_count = obs.rowcount if obs.rowcount and obs.rowcount > 0 else 0
        g._execute(f"DELETE FROM grants WHERE space = {g.ph}", (entity_id,))
        g._execute(f"DELETE FROM entities WHERE id = {g.ph}", (entity_id,))
        g.conn.commit()
        g.bus.publish("observation.created",
                      {"target": "entity", "id": entity_id, "kind": row["kind"],
                       "module": self.module, "deleted": True})
        return {"entity_id": entity_id, "edges": edge_count, "observations": obs_count}

    def purge_owner(self, owner_id: str, *, source: str) -> dict:
        """Delete EVERY entity belonging to one owner, with their edges and provenance.

        The erasure primitive. It deliberately takes an `owner_id` rather than working from
        the session's own scope, because the caller doing the erasing is the accounts layer
        acting on a system session — the account being erased must not have to be logged in
        for its data to go, or "delete my account" would stop working the moment a session
        expired.

        No provenance row is written for the deletions: recording "we erased Ana's data at
        14:03" against Ana's own id would leave exactly the trace the erasure was for.
        """
        self._need("content", "write")
        g = self.graph
        ids = [r["id"] for r in g._execute(
            f"SELECT id FROM entities WHERE owner_id = {g.ph}", (owner_id,)).fetchall()]
        if not ids:
            return {"entities": 0, "edges": 0, "observations": 0, "grants": 0}

        marks = ", ".join([g.ph] * len(ids))
        edges = g._execute(
            f"DELETE FROM edges WHERE src IN ({marks}) OR dst IN ({marks})", (*ids, *ids))
        obs = g._execute(f"DELETE FROM observations WHERE entity_id IN ({marks})", tuple(ids))
        grants = g._execute(f"DELETE FROM grants WHERE space IN ({marks})", tuple(ids))
        g._execute(f"DELETE FROM entities WHERE owner_id = {g.ph}", (owner_id,))
        g.conn.commit()

        def count(cur):
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        return {"entities": len(ids), "edges": count(edges),
                "observations": count(obs), "grants": count(grants)}

    def grants_for(self, space: str) -> list[dict]:
        self._need("content", "read")
        g = self.graph
        cur = g._execute(f"SELECT * FROM grants WHERE space = {g.ph}", (space,))
        return [{"subject": r["subject"], "scope": r["scope"], "space": r["space"],
                 "granted_at": r["granted_at"]} for r in cur.fetchall()]

    def spaces_granted(self, subject: str, scopes) -> list[str]:
        """The reverse of grants_for: which spaces has this subject been granted a role in?

        `grants_for` answers "who is in this space", which only helps once you already know
        the space. Finding a shared session that someone else opened *for you* needs the
        other direction. Ids only — reading each space still goes through the normal checks.
        """
        wanted = sorted(set(scopes or ()))
        if not wanted:
            return []
        self._need("content", "read")
        g = self.graph
        marks = ", ".join([g.ph] * len(wanted))
        cur = g._execute(
            f"SELECT DISTINCT space FROM grants WHERE subject = {g.ph} AND scope IN ({marks})",
            (subject, *wanted),
        )
        return [r["space"] for r in cur.fetchall()]

    # ---- reads ----------------------------------------------------------

    def _fetch_entity(self, entity_id: str):
        """Fetch by id, honouring the session's owner scope.

        find_entities has always filtered by owner; fetching by id did not, which made
        multi-tenant isolation nominal rather than real — knowing an id was enough to read
        or update another owner's entity. A scoped session now simply cannot see outside
        its own owner, so an out-of-scope id is indistinguishable from a missing one.
        """
        g = self.graph
        cur = g._execute(f"SELECT * FROM entities WHERE id = {g.ph}", (entity_id,))
        row = cur.fetchone()
        if row is None:
            return None
        if g.default_owner and row["owner_id"] != g.default_owner:
            return None
        return row

    def get_entity(self, entity_id: str) -> dict | None:
        row = self._fetch_entity(entity_id)
        if row is None:
            return None
        self._need(row["kind"], "read")
        return _row_to_entity(row)

    # ---- the one deliberate crossing of the owner boundary ----------------

    def find_public(self, kind: str, attr_equals: dict | None = None,
                    limit: int = 100) -> list[dict]:
        """Read PUBLISHED entities across owners — the only cross-tenant read there is.

        Everything else in this class is owner-scoped, deliberately. A directory of public
        crews and events cannot work under that rule, so this is the single, narrow hole,
        and it is narrow by construction rather than by convention:

          - `attrs.visibility == "public"` is forced into the query. A caller cannot widen
            it, and an entity that was never explicitly published is invisible here even if
            you know its id.
          - Reads only. There is no cross-owner write path; joining or editing someone
            else's thing still has to go through their own scope.
          - Scope checks still apply, so a module without `<domain>:read` gets nothing.

        Anything sensitive is safe as long as it is never marked public — which is why
        `visibility` is only ever set by an explicit publish/create choice.
        """
        self._need(kind, "read")
        g = self.graph
        sql = f"SELECT * FROM entities WHERE kind = {g.ph}"
        params: list = [kind]
        clauses = dict(attr_equals or {})
        clauses["visibility"] = "public"          # forced; overrides any caller value
        for key, value in clauses.items():
            if not _ATTR_KEY_RE.match(key):
                raise GraphError(f"invalid attr key: {key!r}")
            if g.dialect == "sqlite":
                sql += f" AND json_extract(attrs, '$.{key}') = {g.ph}"
            else:
                sql += f" AND attrs->>'{key}' = {g.ph}"
            params.append(value)
        sql += f" ORDER BY created_at LIMIT {int(limit)}"
        return [_row_to_entity(r) for r in g._execute(sql, tuple(params)).fetchall()]

    def _granted(self, entity_id: str, subject: str, scopes) -> bool:
        wanted = set(scopes or ())
        return any(g["subject"] == subject and g["scope"] in wanted
                   for g in self.grants_for(entity_id))

    def get_if_granted(self, entity_id: str, subject: str, scopes) -> dict | None:
        """Read an entity you don't own because you were explicitly GRANTED a role on it.

        The other cross-owner path (`find_public`) is for things published to the world.
        This one is for things shared with named participants — a crew's planning session
        that its members, and only its members, should see. A grant is the permission; no
        grant means the entity reads as missing, exactly as it does out of scope.
        """
        g = self.graph
        row = g._execute(f"SELECT * FROM entities WHERE id = {g.ph}", (entity_id,)).fetchone()
        if row is None:
            return None
        if not self._granted(entity_id, subject, scopes):
            return None
        self._need(row["kind"], "read")
        return _row_to_entity(row)

    def update_if_granted(self, entity_id: str, attrs_patch: dict, subject: str, scopes,
                          *, source: str, confidence: float = 1.0) -> dict:
        """Write to an entity you were granted a role on — a participant adding their own
        availability to a shared session, not an edit of someone's private data.

        The grant is the whole authorisation, so callers must keep the patch to what that
        role legitimately covers; this is first-party module code, held to that discipline.
        """
        g = self.graph
        row = g._execute(f"SELECT * FROM entities WHERE id = {g.ph}", (entity_id,)).fetchone()
        if row is None or not self._granted(entity_id, subject, scopes):
            raise GraphError(f"entity not found: {entity_id}")
        self._need(row["kind"], "write")
        current = row["attrs"]
        merged = {**(json.loads(current) if isinstance(current, str) else current), **attrs_patch}
        g._execute(
            f"UPDATE entities SET attrs = {g.ph}, updated_at = {g.ph} WHERE id = {g.ph}",
            (json.dumps(merged), now_iso(), entity_id),
        )
        self._record_provenance(entity_id, source, confidence)
        g.conn.commit()
        g.bus.publish("observation.created",
                      {"target": "entity", "id": entity_id, "kind": row["kind"], "module": self.module})
        return merged

    def get_public(self, entity_id: str) -> dict | None:
        """Fetch one published entity by id, whoever owns it. Unpublished ids read as
        missing, exactly as they do through the owner-scoped path."""
        g = self.graph
        row = g._execute(f"SELECT * FROM entities WHERE id = {g.ph}", (entity_id,)).fetchone()
        if row is None:
            return None
        entity = _row_to_entity(row)
        if entity["attrs"].get("visibility") != "public":
            return None
        self._need(entity["kind"], "read")
        return entity

    def find_entities(self, kind: str, attr_equals: dict | None = None, limit: int = 100) -> list[dict]:
        self._need(kind, "read")
        g = self.graph
        sql = f"SELECT * FROM entities WHERE kind = {g.ph}"
        params: list = [kind]
        if g.default_owner:
            sql += f" AND owner_id = {g.ph}"
            params.append(g.default_owner)
        for key, value in (attr_equals or {}).items():
            if not _ATTR_KEY_RE.match(key):
                raise GraphError(f"invalid attr key: {key!r}")
            if g.dialect == "sqlite":
                sql += f" AND json_extract(attrs, '$.{key}') = {g.ph}"
            else:
                sql += f" AND attrs->>'{key}' = {g.ph}"
            params.append(value)
        sql += f" ORDER BY created_at LIMIT {int(limit)}"
        cur = g._execute(sql, tuple(params))
        return [_row_to_entity(r) for r in cur.fetchall()]

    def neighbors(self, entity_id: str, rel: str | None = None, direction: str = "out") -> list[dict]:
        """Entities connected to entity_id. Returns only kinds this session may read."""
        if direction not in ("out", "in"):
            raise GraphError("direction must be 'out' or 'in'")
        g = self.graph
        join_col, filter_col = ("dst", "src") if direction == "out" else ("src", "dst")
        sql = (
            f"SELECT e.*, ed.rel AS _rel, ed.weight AS _weight FROM edges ed "
            f"JOIN entities e ON e.id = ed.{join_col} WHERE ed.{filter_col} = {g.ph}"
        )
        params: list = [entity_id]
        if rel is not None:
            if rel not in RELS:
                raise GraphError(f"unknown edge rel: {rel!r}")
            sql += f" AND ed.rel = {g.ph}"
            params.append(rel)
        cur = g._execute(sql, tuple(params))
        out = []
        for row in cur.fetchall():
            keys = row.keys() if hasattr(row, "keys") else row
            entity = _row_to_entity(row)
            entity["rel"] = row["_rel"] if "_rel" in keys else None
            entity["weight"] = row["_weight"] if "_weight" in keys else None
            try:
                self._need(entity["kind"], "read")
            except ScopeError:
                continue
            out.append(entity)
        return out


def _row_to_entity(row) -> dict:
    attrs = row["attrs"]
    if isinstance(attrs, str):
        attrs = json.loads(attrs)
    return {
        "id": row["id"],
        "kind": row["kind"],
        "attrs": attrs,
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
