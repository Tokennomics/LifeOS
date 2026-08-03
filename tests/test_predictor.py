import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import predictor
from substrate.graph import Graph


def test_relationship_link_predictor(graph: Graph):
    session = graph.session("test", {"*"})
    
    id_a = session.create_entity("person", {"name": "Alice"}, source="test")
    id_b = session.create_entity("person", {"name": "Bob"}, source="test")
    id_int = session.create_entity("interest", {"name": "Surfing"}, source="test")

    # Link both to the interest
    session.create_edge(id_a, id_int, "interested_in", source="test")
    session.create_edge(id_b, id_int, "interested_in", source="test")

    suggestions = predictor.predict_relationships(graph)
    assert len(suggestions) == 1
    assert suggestions[0]["src_id"] == id_a
    assert suggestions[0]["dst_id"] == id_b
    assert "Surfing" in suggestions[0]["reason"]


def test_gateway_predictor_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/predictions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
