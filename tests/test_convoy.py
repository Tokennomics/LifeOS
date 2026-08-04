import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import convoy
from substrate.graph import Graph


def test_convoy_tracking_logic(graph: Graph):
    loc_id = convoy.update_location(graph, "alice", 37.7749, -122.4194, "15 mins", "outing_123")
    assert loc_id is not None

    etas = convoy.get_convoy_etas(graph, "outing_123")
    assert len(etas) == 1
    assert etas[0]["user_id"] == "alice"
    assert etas[0]["eta"] == "15 mins"


def test_gateway_convoy_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "user_id": "bob",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "eta": "10 mins",
        "event_id": "outing_456"
    }
    resp_upd = client.post("/v1/venues/convoy/update", json=payload)
    assert resp_upd.status_code == 200

    resp_etas = client.get("/v1/venues/convoy/etas?event_id=outing_456")
    assert resp_etas.status_code == 200
    assert len(resp_etas.json()) == 1
