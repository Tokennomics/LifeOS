import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.triage import brief
from substrate.graph import Graph


def test_triage_brief_module(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create tasks
    session.create_entity("task", {"title": "Overdue task", "status": "open", "week": "2026-W01"}, source="test")
    session.create_entity("task", {"title": "Stuck task", "status": "open", "carries": 3}, source="test")

    # Create focused goal
    session.create_entity("goal", {"title": "Ship LifeOS v0.1", "focus": True}, source="test")

    res = brief.generate_triage_brief(graph)
    assert "date" in res
    assert res["top_escalation"] is not None
    assert res["top_escalation"]["title"] == "Overdue task"
    assert len(res["stuck_work"]) == 1
    assert res["stuck_work"][0]["title"] == "Stuck task"
    assert len(res["focused_goals"]) == 1
    assert res["focused_goals"][0]["title"] == "Ship LifeOS v0.1"


def test_gateway_triage_brief_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/triage/brief")
    assert resp.status_code == 200
    data = resp.json()
    assert "date" in data
    assert "energy_baseline" in data
    assert "tasks_summary" in data
