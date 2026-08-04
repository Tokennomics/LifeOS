import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import cohort
from substrate.graph import Graph


def test_cohort_streaks_leaderboard(graph: Graph):
    session = graph.session("test", {"*"})
    
    session.create_entity("admin_item", {"type": "routine_milestone", "user_id": "alice", "title": "15-day streak"}, source="test")
    session.create_entity("admin_item", {"type": "routine_milestone", "user_id": "bob", "title": "5-day streak"}, source="test")

    list_ranks = cohort.get_cohort_leaderboard(graph, "routine_999")
    assert len(list_ranks) == 2
    assert list_ranks[0]["user_id"] == "alice"
    assert list_ranks[0]["streak_days"] == 15


def test_gateway_cohort_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/routines/cohort/leaderboard?routine_id=routine_999")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
