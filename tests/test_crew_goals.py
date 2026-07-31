import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import crew_goals
from substrate.graph import Graph


def test_crew_joint_goals(graph: Graph):
    session = graph.session("test", {"*"})
    crew_id = session.create_entity("person", {"name": "Alpha Crew", "type": "crew"}, source="test")

    res = crew_goals.create_crew_goal(graph, crew_id, "Climb Mt. Everest", "2026-12-31")
    assert res["status"] == "active"
    assert res["crew_id"] == crew_id


def test_gateway_crew_goals_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "crew_id": "crew_123",
        "title": "Launch Startup",
        "target_date": "2026-09-30"
    }
    resp = client.post("/v1/horizon/crew-goals", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
