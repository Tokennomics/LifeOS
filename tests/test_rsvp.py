import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import rsvp
from substrate.graph import Graph


def test_outing_rsvp_submission_and_retrieval(graph: Graph):
    rsvp_id = rsvp.submit_rsvp(graph, "event_123", "alice", "accepted")
    assert rsvp_id is not None

    rsvps = rsvp.list_rsvps(graph, "event_123")
    assert len(rsvps) == 1
    assert rsvps[0]["user_id"] == "alice"
    assert rsvps[0]["status"] == "accepted"


def test_gateway_rsvp_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "event_id": "event_99",
        "user_id": "bob",
        "status": "tentative"
    }
    resp_sub = client.post("/v1/venues/rsvp", json=payload)
    assert resp_sub.status_code == 200

    resp_list = client.get("/v1/venues/rsvp/list?event_id=event_99")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1
