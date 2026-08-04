import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import chaining
from substrate.graph import Graph


def test_habit_chaining_suggestions(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Baseline checks
    res_base = chaining.suggest_habit_chain(graph)
    assert res_base["habit_anchor"] == "Morning Coffee"

    # Seed some task history
    session.create_entity("task", {"title": "Brush Teeth"}, source="test")
    session.create_entity("task", {"title": "Floss"}, source="test")

    res_chain = chaining.suggest_habit_chain(graph)
    assert res_chain["habit_anchor"] == "Brush Teeth"
    assert res_chain["habit_target"] == "Floss"


def test_gateway_chaining_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post("/v1/routines/chaining-recommendation")
    assert resp.status_code == 200
    assert "habit_anchor" in resp.json()
