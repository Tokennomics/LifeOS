import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import voting
from substrate.graph import Graph


def test_venue_voting_logic(graph: Graph):
    res_a = voting.submit_vote(graph, "outing1", "cafe_123", "alice")
    assert res_a["status"] == "Vote recorded."

    res_b = voting.submit_vote(graph, "outing1", "bar_456", "bob")
    res_c = voting.submit_vote(graph, "outing1", "cafe_123", "charlie")

    results = voting.get_poll_results(graph, "outing1")
    assert results["total_votes"] == 3
    assert results["winner_place_id"] == "cafe_123"


def test_gateway_voting_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "poll_id": "outing2",
        "place_id": "park_789",
        "member_id": "alice"
    }
    resp_vote = client.post("/v1/venues/vote", json=payload)
    assert resp_vote.status_code == 200

    resp_res = client.get("/v1/venues/vote/results?poll_id=outing2")
    assert resp_res.status_code == 200
    assert resp_res.json()["winner_place_id"] == "park_789"
