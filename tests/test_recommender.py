import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import recommender
from substrate.graph import Graph


def test_places_recommendation_ranking(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Setup matching interests and places
    session.create_entity("interest", {"name": "coffee"}, source="test")
    session.create_entity("interest", {"name": "music"}, source="test")

    session.create_entity("place", {"name": "Jazz Coffee Bar", "category": "Cafe", "description": "Great music and fresh coffee"}, source="test")
    session.create_entity("place", {"name": "Book Library", "category": "Education", "description": "Quiet place for studying"}, source="test")

    recs = recommender.recommend_places(graph)
    assert len(recs) >= 2
    # The first one should be "Jazz Coffee Bar" because it matches coffee and music
    assert recs[0]["name"] == "Jazz Coffee Bar"
    assert recs[0]["match_score"] > 1.0


def test_gateway_recommendations_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/venues/recommendations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
