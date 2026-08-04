import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import clusters
from substrate.graph import Graph


def test_social_cliques_detection(graph: Graph):
    session = graph.session("test", {"*"})
    
    id_a = session.create_entity("person", {"name": "Alice"}, source="test")
    id_b = session.create_entity("person", {"name": "Bob"}, source="test")

    session.create_edge(id_a, id_b, "with", source="test")

    list_cliques = clusters.detect_social_cliques(graph)
    assert len(list_cliques) == 1
    assert id_a in list_cliques[0]
    assert id_b in list_cliques[0]


def test_gateway_clusters_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/social-clusters")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
