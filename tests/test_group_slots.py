import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import group_slots
from substrate.graph import Graph


def test_group_slots_optimization(graph: Graph):
    slots = group_slots.optimize_group_slots(graph, "outing_123")
    assert len(slots) >= 2


def test_gateway_group_slots_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/venues/rsvp-slots?event_id=outing_123")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
