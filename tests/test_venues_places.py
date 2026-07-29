import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import places
from substrate.graph import Graph


def test_venue_search_and_linking(graph: Graph):
    # Search venues
    results = places.search_venues("climbing", city="Lisbon")
    assert len(results) >= 1
    venue = results[0]
    assert "place_id" in venue
    assert "google_maps_url" in venue

    # Details lookup
    details = places.get_venue_details(venue["place_id"])
    assert details["place_id"] == venue["place_id"]
    assert "google_maps_url" in details

    # Create target event entity first (Graph invariant: both endpoints must exist)
    session = graph.session("test", {"*"})
    target_event_id = session.create_entity("event", {"title": "Lisbon Climb Meetup"}, source="test")

    # Graph linking to target crew event
    link_res = places.link_venue(graph, target_event_id, venue)
    assert link_res["target_id"] == target_event_id
    assert link_res["place_id"] == venue["place_id"]

    # Verify place entity exists in graph
    places_entities = session.find_entities("place", {"place_id": venue["place_id"]})
    assert len(places_entities) == 1
    assert places_entities[0]["attrs"]["name"] == venue["name"]


def test_gateway_venue_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    # Search endpoint
    resp_s = client.get("/v1/venues/search?query=sushi&city=Lisbon")
    assert resp_s.status_code == 200
    venues = resp_s.json()
    assert len(venues) >= 1

    place_id = venues[0]["place_id"]

    # Details endpoint
    resp_d = client.get(f"/v1/venues/{place_id}")
    assert resp_d.status_code == 200
    assert resp_d.json()["place_id"] == place_id

    # Create event via gateway or graph for linking endpoint test
    # First get graph from app state to create event endpoint
    graph = app.state.graph
    session = graph.session("test", {"*"})
    target_event_id = session.create_entity("event", {"title": "Sushi Night Event"}, source="test")

    # Link endpoint
    payload = {
        "target_id": target_event_id,
        "place_info": venues[0],
    }
    resp_l = client.post("/v1/venues/link", json=payload)
    assert resp_l.status_code == 200
    assert resp_l.json()["target_id"] == target_event_id
