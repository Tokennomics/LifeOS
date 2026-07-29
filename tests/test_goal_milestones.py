import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import milestones
from substrate.graph import Graph


def test_goal_milestones_and_progress(graph: Graph):
    session = graph.session("test", {"*"})
    goal_id = session.create_entity("goal", {"title": "Ship LifeOS App", "level": "goal"}, source="test")

    # Add milestone
    ms = milestones.add_milestone(graph, goal_id, "Ship v0.1 Gateway", target_week="2026-W30")
    assert ms["status"] == "open"

    # Add task
    session.create_entity("task", {"title": "Build milestones module", "status": "completed", "goal_id": goal_id}, source="test")

    progress1 = milestones.goal_progress(graph, goal_id)
    assert progress1["milestones"]["total"] == 1
    assert progress1["milestones"]["completed"] == 0
    assert progress1["tasks"]["total"] == 1
    assert progress1["tasks"]["completed"] == 1
    assert progress1["progress_percent"] == 40.0

    # Complete milestone
    milestones.complete_milestone(graph, ms["id"])
    progress2 = milestones.goal_progress(graph, goal_id)
    assert progress2["milestones"]["completed"] == 1
    assert progress2["progress_percent"] == 100.0


def test_gateway_goal_milestones_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    # 1. Create goal via vision
    resp_v = client.post("/v1/vision", json={"text": "Goal Test\n- Ship Milestones"})
    assert resp_v.status_code == 200

    # Retrieve goal from graph
    g = app.state.graph
    session = g.session("test", {"*"})
    goals = session.find_entities("goal")
    assert len(goals) >= 1
    goal_id = goals[0]["id"]

    # 2. Add milestone
    resp_ms = client.post(f"/v1/goals/{goal_id}/milestones", json={"title": "Deliver v1", "target_week": "2026-W30"})
    assert resp_ms.status_code == 200
    ms = resp_ms.json()
    assert ms["title"] == "Deliver v1"

    # 3. Get progress
    resp_p = client.get(f"/v1/goals/{goal_id}/progress")
    assert resp_p.status_code == 200
    assert resp_p.json()["milestones"]["total"] == 1

    # 4. Complete milestone
    resp_c = client.post(f"/v1/milestones/{ms['id']}/complete")
    assert resp_c.status_code == 200
    assert resp_c.json()["status"] == "completed"
