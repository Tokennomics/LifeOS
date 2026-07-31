import pytest
from fastapi.testclient import TestClient
from gateway.main import create_app
from substrate import topology
from substrate.graph import Graph


def test_topology_export(graph: Graph):
    # Populate mock entities and edges
    session = graph.session("test", {"*"})
    id_a = session.create_entity("person", {"name": "Node A"}, source="test")
    id_b = session.create_entity("person", {"name": "Node B"}, source="test")
    session.create_edge(id_a, id_b, "with", source="test")

    res = topology.export_graph_topology(graph)
    assert "nodes" in res
    assert "links" in res
    assert len(res["nodes"]) >= 2
    assert len(res["links"]) >= 1


def test_gateway_topology_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)
    resp = client.get("/v1/graph/topology")
    assert resp.status_code == 200
    assert "nodes" in resp.json()
