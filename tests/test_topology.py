import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import topology
from substrate.graph import Graph


def test_topology_hubs_degree_sorting(graph: Graph):
    session = graph.session("test", {"*"})
    
    id_p = session.create_entity("person", {"name": "Bob"}, source="test")
    id_v1 = session.create_entity("place", {"name": "Climbing Gym"}, source="test")
    id_v2 = session.create_entity("place", {"name": "Coffee Shop"}, source="test")

    session.create_edge(id_p, id_v1, "located_at", source="test")
    session.create_edge(id_p, id_v2, "located_at", source="test")

    hubs = topology.find_topology_hubs(graph)
    assert len(hubs) >= 3
    # Bob has 2 connections, the places have 1 each, so Bob is the main hub node
    assert hubs[0]["entity_id"] == id_p
    assert hubs[0]["connections_count"] == 2


def test_gateway_topology_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/topology-hubs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
