import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.dating import mutual_match
from substrate.graph import Graph


def test_mutual_match_privacy_and_consent(graph: Graph):
    # Single side interest
    res1 = mutual_match.express_interest(graph, target_account_id="acc-user2", activity_id="sushi-night")
    assert res1["outcome"] == "stored_privately"
    assert res1["is_mutual"] is False

    # Reciprocal interest from user2
    user2_session = graph.session("dating", {"*"})
    user2_session.create_entity(
        "content",
        {"type": "dating_intent", "user_id": "acc-user2", "target": graph.default_owner, "activity": "sushi-night", "visibility": "private"},
        source="dating",
    )

    res2 = mutual_match.express_interest(graph, target_account_id="acc-user2", activity_id="sushi-night")
    assert res2["outcome"] == "mutual_match"
    assert res2["is_mutual"] is True

    # Verify matches list
    matches = mutual_match.check_matches(graph)
    assert len(matches) == 1
    assert matches[0]["target_account_id"] == "acc-user2"


def test_gateway_dating_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp_i = client.post("/v1/dating/interest", json={"target_account_id": "acc-user2", "activity_id": "climbing-crew"})
    assert resp_i.status_code == 200
    assert resp_i.json()["outcome"] in ("stored_privately", "mutual_match")

    resp_m = client.get("/v1/dating/matches")
    assert resp_m.status_code == 200
    assert "matches" in resp_m.json()
