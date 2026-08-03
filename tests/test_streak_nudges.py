import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import streak_nudges
from substrate.graph import Graph


def test_streak_nudges_triggering(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create routine streak record with active streak and not completed today
    session.create_entity("admin_item", {"type": "routine_streak", "name": "Gym Routine", "streak": 5, "completed_today": False}, source="test")

    res = streak_nudges.trigger_streak_nudges(graph)
    assert len(res) == 1
    assert res[0]["streak"] == 5
    assert "Gym Routine" in res[0]["message"]


def test_gateway_streak_nudge_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post("/v1/routines/streak-nudge")
    assert resp.status_code == 200
