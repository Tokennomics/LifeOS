import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import cleaner
from substrate.graph import Graph


def test_graph_stale_records_pruner(graph: Graph):
    session = graph.session("test", {"*"})
    
    session.create_entity("admin_item", {"type": "convoy_position", "user_id": "alice"}, source="test")
    
    res = cleaner.prune_graph_stale_records(graph)
    assert res["pruned_entities"] == 1


def test_gateway_pruner_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post("/v1/graph/prune")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
