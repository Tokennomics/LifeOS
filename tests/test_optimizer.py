import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import optimizer
from substrate.graph import Graph


def test_outing_route_optimizer(graph: Graph):
    session = graph.session("test", {"*"})
    
    id_a = session.create_entity("place", {"name": "Cafe A", "lat": 1.0, "lng": 1.0}, source="test")
    id_b = session.create_entity("place", {"name": "Bar B", "lat": 3.0, "lng": 3.0}, source="test")
    id_c = session.create_entity("place", {"name": "Park C", "lat": 1.1, "lng": 1.1}, source="test")

    # Start from A, C is closer than B, so C must be visited before B.
    optimized = optimizer.optimize_outing_route(graph, [id_a, id_b, id_c])
    assert len(optimized) == 3
    assert optimized[0]["place_id"] == id_a
    assert optimized[1]["place_id"] == id_c
    assert optimized[2]["place_id"] == id_b


def test_gateway_optimizer_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {"place_ids": ["place_1", "place_2"]}
    resp = client.post("/v1/venues/optimize-itinerary", json=payload)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
