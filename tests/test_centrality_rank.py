import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import centrality_rank
from substrate.graph import Graph


def test_centrality_rank_computations(graph: Graph):
    session = graph.session("test", {"*"})
    
    id_p = session.create_entity("person", {"name": "Bob"}, source="test")
    id_v1 = session.create_entity("place", {"name": "Climbing Gym"}, source="test")
    id_v2 = session.create_entity("place", {"name": "Coffee Shop"}, source="test")

    session.create_edge(id_p, id_v1, "located_at", source="test")
    session.create_edge(id_p, id_v2, "located_at", source="test")

    ranks = centrality_rank.rank_nodes_centrality(graph)
    assert len(ranks) >= 3
    assert ranks[0]["entity_id"] == id_p
    assert ranks[0]["centrality_ratio"] == 0.5


def test_gateway_centrality_ranks_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/centrality-ranks")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
