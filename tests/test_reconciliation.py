import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.travel import reconcile
from substrate.graph import Graph


def test_reconcile_module_logic(graph: Graph):
    bundle = {
        "schema": "lifeos-travel-export/v1",
        "exported_at": "2026-07-28T12:00:00Z",
        "source": "travel",
        "items": [
            {
                "key": "task-uuid-1",
                "type": "entity",
                "kind": "task",
                "attrs": {"title": "Travel task 1", "status": "open"},
                "ts": "2026-07-28T09:00:00Z",
            },
            {
                "key": "goal-uuid-2",
                "type": "entity",
                "kind": "goal",
                "attrs": {"title": "Travel Goal 1", "level": "goal"},
                "ts": "2026-07-28T09:01:00Z",
            },
            {
                "key": "edge-uuid-3",
                "type": "edge",
                "src": "task-uuid-1",
                "dst": "goal-uuid-2",
                "rel": "feeds",
                "ts": "2026-07-28T09:02:00Z",
            },
        ],
    }

    # First import
    res1 = reconcile.reconcile(graph, bundle)
    assert res1["entities_imported"] == 2
    assert res1["edges_imported"] == 1
    assert res1["skipped"] == 0

    # Verify entities exist in database with original IDs and timestamps
    session = graph.session("test", {"*"})
    t1 = session.get_entity("task-uuid-1")
    assert t1 is not None
    assert t1["kind"] == "task"
    assert t1["attrs"]["title"] == "Travel task 1"
    assert t1["created_at"] == "2026-07-28T09:00:00Z"

    g2 = session.get_entity("goal-uuid-2")
    assert g2 is not None
    assert g2["kind"] == "goal"
    assert g2["created_at"] == "2026-07-28T09:01:00Z"

    # Verify edge exists in database
    cur = graph._execute(f"SELECT * FROM edges WHERE id = {graph.ph}", ("edge-uuid-3",))
    edge_row = cur.fetchone()
    assert edge_row is not None
    assert edge_row["src"] == "task-uuid-1"
    assert edge_row["dst"] == "goal-uuid-2"
    assert edge_row["rel"] == "feeds"
    assert edge_row["created_at"] == "2026-07-28T09:02:00Z"

    # Second import (Idempotency check)
    res2 = reconcile.reconcile(graph, bundle)
    assert res2["entities_imported"] == 0
    assert res2["edges_imported"] == 0
    assert res2["skipped"] == 3


def test_reconcile_invalid_schema(graph: Graph):
    bundle = {
        "schema": "lifeos-travel-export/v2",
        "exported_at": "2026-07-28T12:00:00Z",
        "source": "travel",
        "items": [],
    }
    with pytest.raises(ValueError, match="Unsupported bundle schema"):
        reconcile.reconcile(graph, bundle)


def test_gateway_import_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    bundle = {
        "schema": "lifeos-travel-export/v1",
        "exported_at": "2026-07-28T12:00:00Z",
        "source": "travel",
        "items": [
            {
                "key": "task-uuid-endpoint-1",
                "type": "entity",
                "kind": "task",
                "attrs": {"title": "Endpoint task 1"},
                "ts": "2026-07-28T09:00:00Z",
            }
        ],
    }

    # Test POST /v1/import
    resp = client.post("/v1/import", json=bundle)
    assert resp.status_code == 200
    res = resp.json()
    assert res["entities_imported"] == 1
    assert res["edges_imported"] == 0
    assert res["skipped"] == 0

    # Repeat post should skip
    resp2 = client.post("/v1/import", json=bundle)
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["entities_imported"] == 0
    assert res2["skipped"] == 1
