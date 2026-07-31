import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import centrality
from substrate.graph import Graph


def test_graph_centrality_calculation(graph: Graph):
    session = graph.session("test", {"*"})
    
    id_a = session.create_entity("person", {"name": "Alice"}, source="test")
    id_b = session.create_entity("person", {"name": "Bob"}, source="test")
    id_c = session.create_entity("person", {"name": "Charlie"}, source="test")

    session.create_edge(id_a, id_b, "with", source="test")
    session.create_edge(id_a, id_c, "with", source="test")

    rankings = centrality.calculate_centrality(graph)
    assert len(rankings) >= 3
    # Alice should be ranked first because she has 2 edge connections
    assert rankings[0]["entity_id"] == id_a
    assert rankings[0]["centrality_score"] == 2


def test_gateway_centrality_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/centrality")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
