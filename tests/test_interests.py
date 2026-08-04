import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import interests
from substrate.graph import Graph


def test_local_interest_recommendations(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create user interest and nearby matching place
    session.create_entity("interest", {"name": "Climbing"}, source="test")
    session.create_entity("place", {"name": "Climbing Gym", "lat": 37.7749, "lon": -122.4194}, source="test")

    recs = interests.recommend_local_interests(graph, 37.7749, -122.4194)
    assert len(recs) == 1
    assert recs[0]["name"] == "Climbing Gym"
    assert "climbing" in recs[0]["matching_interests"]


def test_gateway_interests_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/venues/interests-local?lat=37.7749&lon=-122.4194")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
