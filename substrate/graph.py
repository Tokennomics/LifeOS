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

    def _record_provenance(self, target_id: str, source: str, confidence: float) -> None:
        if not source:
            raise ProvenanceError("every graph write needs a source")
        if not (0.0 <= confidence <= 1.0):
            raise ProvenanceError(f"confidence must be in [0,1], got {confidence}")
        g = self.graph
        g._execute(
            f"INSERT INTO observations (id, entity_id, module, confidence, source, created_at) "
            f"VALUES ({g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph})",
            (new_id(), target_id, self.module, confidence, source, now_iso()),
        )

    # ---- writes ---------------------------------------------------------

    def create_entity(self, kind: str, attrs: dict | None = None, *, source: str,
                      confidence: float = 1.0, owner_id: str | None = None,
                      entity_id: str | None = None) -> str:
        self._need(kind, "write")
        owner = owner_id or self.graph.default_owner
        if not owner:
            raise GraphError("owner_id required (no default owner configured)")
        g = self.graph
        eid = entity_id or new_id()
        ts = now_iso()
        g._execute(
            f"INSERT INTO entities (id, kind, attrs, owner_id, created_at, updated_at) "
            f"VALUES ({g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph})",
            (eid, kind, json.dumps(attrs or {}), owner, ts, ts),
        )
        self._record_provenance(eid, source, confidence)
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
                    attrs: dict | None = None, source: str, confidence: float = 1.0) -> str:
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
        edge_id = new_id()
        g._execute(
            f"INSERT INTO edges (id, src, dst, rel, weight, attrs, created_at) "
            f"VALUES ({g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph}, {g.ph})",
            (edge_id, src, dst, rel, weight, json.dumps(attrs or {}), now_iso()),
        )
        self._record_provenance(edge_id, source, confidence)
        g.conn.commit()
        g.bus.publish("observation.created", {"target": "edge", "id": edge_id, "rel": rel, "module": self.module})
        return edge_id

    # ---- reads ----------------------------------------------------------

    def _fetch_entity(self, entity_id: str):
        g = self.graph
        cur = g._execute(f"SELECT * FROM entities WHERE id = {g.ph}", (entity_id,))
        return cur.fetchone()

    def get_entity(self, entity_id: str) -> dict | None:
        row = self._fetch_entity(entity_id)
        if row is None:
            return None
        self._need(row["kind"], "read")
        return _row_to_entity(row)

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
