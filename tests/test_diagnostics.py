import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.health import diagnostics
from substrate.graph import Graph


def test_graph_diagnostics_scanner(graph: Graph):
    session = graph.session("test", {"*"})
    session.create_entity("goal", {"title": "Diagnostic Target"}, source="test")

    res = diagnostics.run_diagnostics(graph)
    assert res["healthy"] is True
    assert res["total_entities"] >= 1
    assert "entities_by_kind" in res


def test_gateway_diagnostics_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/health/diagnostics")
    assert resp.status_code == 200
    assert resp.json()["healthy"] is True
    assert "entities_by_kind" in resp.json()
