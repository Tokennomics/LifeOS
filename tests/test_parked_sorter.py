import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import parked_sorter
from substrate.graph import Graph


def test_parked_idea_promotion(graph: Graph):
    session = graph.session("test", {"*"})
    idea_id = session.create_entity("content", {"type": "parked_idea", "text": "Build dating app", "status": "parked"}, source="test")

    parked_list = parked_sorter.list_parked(graph)
    assert len(parked_list) == 1
    assert parked_list[0]["id"] == idea_id

    # Promote to goal
    res = parked_sorter.promote_parked(graph, idea_id, target_level="goal")
    assert res["idea_id"] == idea_id
    assert res["target_level"] == "goal"

    # Verify no longer in open parked list
    assert len(parked_sorter.list_parked(graph)) == 0


def test_gateway_parked_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/parked")
    assert resp.status_code == 200
    assert "parked" in resp.json()
