import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import rings
from substrate.graph import Graph


def test_habit_rings_aggregation(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Baseline checks
    res_base = rings.calculate_habit_rings(graph)
    assert res_base["rings"]["mindfulness"] == 0.0

    # Seed some completed habits
    session.create_entity("task", {"title": "Breathwork session", "completed_today": True}, source="test")
    session.create_entity("task", {"title": "Run 5km", "status": "completed"}, source="test")

    res_rings = rings.calculate_habit_rings(graph)
    assert res_rings["rings"]["mindfulness"] == 50.0 # 1 out of 2 completed
    assert res_rings["rings"]["physical"] == 100.0 # 1 out of 1 completed


def test_gateway_rings_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/routines/rings")
    assert resp.status_code == 200
    assert "rings" in resp.json()
