import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import audit
from substrate.graph import Graph


def test_chronological_audit_timeline(graph: Graph):
    session = graph.session("test", {"*"})
    
    session.create_entity("goal", {"title": "Climb V5"}, source="test")
    session.create_entity("task", {"title": "Do pullups"}, source="test")

    timeline = audit.generate_audit_timeline(graph)
    assert len(timeline) >= 2
    assert timeline[0]["label"] in {"Climb V5", "Do pullups"}


def test_gateway_audit_timeline_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/timeline")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
