import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import milestones
from substrate.graph import Graph


def test_milestone_award_operations(graph: Graph):
    ms_id = milestones.award_milestone(graph, "alice", "10-day streak", "Completed tasks for 10 straight days")
    assert ms_id is not None

    list_ms = milestones.list_milestones(graph, "alice")
    assert len(list_ms) == 1
    assert list_ms[0]["title"] == "10-day streak"


def test_gateway_milestone_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "user_id": "bob",
        "title": "Meditation Master",
        "description": "50 sessions completed"
    }
    resp_award = client.post("/v1/routines/milestone-achieved", json=payload)
    assert resp_award.status_code == 200

    resp_list = client.get("/v1/routines/milestones/list?user_id=bob")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1
