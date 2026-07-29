import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import auto_planner
from substrate.graph import Graph


def test_auto_draft_week_plan(graph: Graph):
    session = graph.session("test", {"*"})
    session.create_entity("goal", {"title": "Build Scaling Engine", "focus": True}, source="test")

    res = auto_planner.auto_draft_week_plan(graph, week="W02")
    assert res["week"] == "W02"
    assert res["created_tasks_count"] >= 2


def test_gateway_auto_planner_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post("/v1/horizon/planner/auto-draft?week=W03")
    assert resp.status_code == 200
    assert resp.json()["week"] == "W03"
