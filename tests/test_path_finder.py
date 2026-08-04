import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import path_finder
from substrate.graph import Graph


def test_social_pathfinder_logic(graph: Graph):
    session = graph.session("test", {"*"})
    
    id_a = session.create_entity("person", {"name": "Alice"}, source="test")
    id_b = session.create_entity("person", {"name": "Bob"}, source="test")
    id_c = session.create_entity("person", {"name": "Charlie"}, source="test")

    session.create_edge(id_a, id_b, "with", source="test")
    session.create_edge(id_b, id_c, "with", source="test")

    path = path_finder.find_social_paths(graph, id_a, id_c)
    assert path == [id_a, id_b, id_c]


def test_gateway_pathfinder_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/paths?src_id=alice&dst_id=bob")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
