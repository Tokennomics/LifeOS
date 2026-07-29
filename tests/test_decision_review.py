import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.calibre import decisions, review
from substrate.graph import Graph


def test_decision_outcome_review(graph: Graph):
    d_id = decisions.log(
        graph,
        title="Hire remote lead",
        choice="Hire Candidate A",
        confidence=0.8,
        predicted="Will accelerate ship speed by 20%",
        review_days=0,
    )

    pending = review.pending_reviews(graph)
    assert len(pending) == 1
    assert pending[0]["id"] == d_id
    assert pending[0]["due_for_review"] is True

    # Record outcome
    res = review.record_outcome(graph, d_id, happened=True, reflection="Accelerated shipping as expected")
    assert res["status"] == "resolved"
    assert res["happened"] is True
    assert res["calibration_error"] == 0.2


def test_gateway_decision_review_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    g = app.state.graph
    d_id = decisions.log(g, title="Test Decision", choice="Option 1", confidence=0.7, predicted="P", review_days=0)

    resp_p = client.get("/v1/decisions/pending")
    assert resp_p.status_code == 200
    assert len(resp_p.json()["pending"]) >= 1

    resp_o = client.post(f"/v1/decisions/{d_id}/outcome", json={"happened": True, "reflection": "Good call"})
    assert resp_o.status_code == 200
    assert resp_o.json()["status"] == "resolved"
