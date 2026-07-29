import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import analytics
from substrate.graph import Graph


def test_goal_velocity_analytics(graph: Graph):
    session = graph.session("test", {"*"})
    goal_id = session.create_entity("goal", {"title": "Build AI Features"}, source="test")

    session.create_entity("task", {"title": "Task 1", "status": "completed", "week": "2026-W28", "goal_id": goal_id}, source="test")
    session.create_entity("task", {"title": "Task 2", "status": "completed", "week": "2026-W29", "goal_id": goal_id}, source="test")

    res = analytics.goal_velocity(graph)
    assert res["total_goals"] == 1
    g_info = res["goals"][0]
    assert g_info["goal_id"] == goal_id
    assert g_info["total_completed"] == 2
    assert g_info["weekly_velocity"] == 1.0


def test_gateway_goal_velocity_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/goals/velocity")
    assert resp.status_code == 200
    assert "goals" in resp.json()
