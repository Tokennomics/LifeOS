import pytest
from fastapi.testclient import TestClient
from gateway.main import create_app
from modules.venues import itinerary_builder
from substrate.graph import Graph


def test_crew_itinerary_generation(graph: Graph):
    session = graph.session("test", {"*"})
    vid_1 = session.create_entity("place", {"name": "Coffee House", "address": "123 Main St"}, source="test")
    vid_2 = session.create_entity("place", {"name": "Retro Bar", "address": "456 Oak Ave"}, source="test")

    res = itinerary_builder.generate_crew_itinerary(graph, [vid_1, vid_2], "2026-07-29T18:00:00Z")
    assert "itinerary_id" in res
    assert len(res["stops"]) == 2
    assert res["stops"][0]["name"] == "Coffee House"
    assert res["stops"][1]["name"] == "Retro Bar"


def test_gateway_itinerary_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)
    payload = {
        "venue_ids": ["v1", "v2"],
        "start_time": "2026-07-29T19:00:00Z"
    }
    resp = client.post("/v1/venues/itinerary/generate", json=payload)
    assert resp.status_code == 200
    assert "itinerary_id" in resp.json()
