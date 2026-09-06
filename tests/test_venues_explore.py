import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import explore
from substrate.graph import Graph


def test_venues_exploration_and_saving(graph: Graph):
    # Explore Lisbon with specific interests
    results = explore.explore_city_venues(graph, "Lisbon", interests_override=["coffee", "climbing"])
    
    # Verify we get the pre-seeded Copenhagen Coffee Lab and Escala 25 climbing gym
    assert len(results) == 2
    names = {r["name"] for r in results}
    assert "Copenhagen Coffee Lab Lisbon" in names
    assert "Escala 25 Climbing Gym" in names
    
    # Save Copenhagen Coffee Lab to graph
    coffee_lab = [r for r in results if r["name"] == "Copenhagen Coffee Lab Lisbon"][0]
    save_res = explore.save_explored_place(graph, coffee_lab)
    assert save_res["saved"] is True
    assert "entity_id" in save_res
    
    # Verify it exists in graph
    session = graph.session("venues", {"*"})
    stored = session.get_entity(save_res["entity_id"])
    assert stored is not None
    assert stored["attrs"]["name"] == "Copenhagen Coffee Lab Lisbon"
    assert stored["attrs"]["address"] == "Rua Nova da Piedade 10, Lisbon"
    
    # Attempting to save again does not duplicate, returns saved=False
    save_again = explore.save_explored_place(graph, coffee_lab)
    assert save_again["saved"] is False
    assert save_again["entity_id"] == save_res["entity_id"]


def test_gateway_explore_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    # Test GET /v1/venues/explore
    #
    # The endpoint returned a bare list while the PWA read `res.venues`, so Explore rendered
    # nothing even on the rare page load where the request did not 422 for a missing `city`.
    # Two silent mismatches stacked on one feature; this test only ever saw the first half
    # because it passed a city and indexed the list directly.
    resp_e = client.get("/v1/venues/explore?city=Lisbon&interests=coffee,hiking")
    assert resp_e.status_code == 200
    body = resp_e.json()
    assert body["city"] == "Lisbon"
    places = body["venues"]
    assert len(places) >= 1
    
    # Test POST /v1/venues/explore/save
    payload = {
        "place_info": places[0]
    }
    resp_s = client.post("/v1/venues/explore/save", json=payload)
    assert resp_s.status_code == 200
    assert resp_s.json()["saved"] is True
