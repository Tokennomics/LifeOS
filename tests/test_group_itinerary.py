import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import group_itinerary
from substrate.graph import Graph


def test_group_itinerary_proposals(graph: Graph):
    node_id = group_itinerary.propose_itinerary_node(graph, "outing_123", "venue_456", 1)
    assert node_id is not None

    timeline = group_itinerary.get_itinerary(graph, "outing_123")
    assert len(timeline) == 1
    assert timeline[0]["venue_id"] == "venue_456"
    assert timeline[0]["sequence_order"] == 1


def test_gateway_itinerary_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "event_id": "outing_789",
        "venue_id": "venue_abc",
        "sequence_order": 2
    }
    resp_prop = client.post("/v1/venues/itinerary/propose", json=payload)
    assert resp_prop.status_code == 200

    resp_list = client.get("/v1/venues/itinerary/list?event_id=outing_789")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1
