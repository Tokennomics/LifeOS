import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import energy_balance
from substrate.graph import Graph


def test_energy_balance_analytics(graph: Graph):
    session = graph.session("test", {"*"})
    session.create_entity("task", {"title": "Task 1", "status": "open"}, source="test")
    session.create_entity("goal", {"title": "Goal 1", "focus": True}, source="test")

    res = energy_balance.get_energy_balance(graph)
    assert res["open_tasks_count"] >= 1
    assert res["active_goals_count"] >= 1
    assert "burnout_risk" in res
    assert "recommendation" in res


def test_gateway_energy_balance_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/horizon/energy-balance")
    assert resp.status_code == 200
    assert "burnout_risk" in resp.json()
    assert "cognitive_load_index" in resp.json()
