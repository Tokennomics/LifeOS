import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import progress_model
from substrate.graph import Graph


def test_goal_progress_projection(graph: Graph):
    session = graph.session("test", {"*"})
    
    gid = session.create_entity("goal", {"title": "Master Rust Programming", "level": "goal"}, source="test")
    
    # Associated tasks
    session.create_entity("task", {"title": "Read Chapter 1", "goal_id": gid, "status": "completed"}, source="test")
    session.create_entity("task", {"title": "Write basic parser", "goal_id": gid, "status": "pending"}, source="test")

    res = progress_model.project_goal_completion(graph, gid)
    assert res["goal_id"] == gid
    assert res["completion_percentage"] == 50.0
    assert res["projected_completion_date"] != "unknown"


def test_gateway_projection_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    graph = app.state.graph
    session = graph.session("test", {"*"})
    gid = session.create_entity("goal", {"title": "Gateway Test Goal", "level": "goal"}, source="test")

    resp = client.get(f"/v1/goals/{gid}/projection")
    assert resp.status_code == 200
    assert "projected_completion_date" in resp.json()
