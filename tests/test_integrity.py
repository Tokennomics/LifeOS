import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import integrity
from substrate.graph import Graph


def test_graph_link_integrity_check(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Empty database has no entities and no edges -> healthy baseline 100.0%
    res = integrity.audit_graph_integrity(graph)
    assert res["integrity_score"] == 100.0


def test_gateway_integrity_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/integrity")
    assert resp.status_code == 200
    assert "integrity_score" in resp.json()
