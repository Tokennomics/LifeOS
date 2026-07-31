import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import graphml_exporter
from substrate.graph import Graph


def test_graphml_generation(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create entities and edges
    id_a = session.create_entity("person", {"name": "Alice"}, source="test")
    id_b = session.create_entity("person", {"name": "Bob"}, source="test")
    session.create_edge(id_a, id_b, "with", source="test")

    xml_content = graphml_exporter.export_graphml(graph)
    assert "<graphml" in xml_content
    assert f'id="{id_a}"' in xml_content
    assert f'id="{id_b}"' in xml_content
    assert "source" in xml_content
    assert "target" in xml_content


def test_gateway_graphml_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/graph/export/graphml")
    assert resp.status_code == 200
    assert "xml" in resp.headers["content-type"]
