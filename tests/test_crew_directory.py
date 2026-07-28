import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.crews import crews
from substrate.graph import Graph


def test_crew_directory(graph: Graph):
    session = graph.session("test", {"*"})
    crews.create(graph, name="Lisbon Bouldering", topic="climbing", city="Lisbon", visibility="public")

    res = crews.directory(graph, topic="climbing", city="Lisbon")
    assert len(res) >= 1
    assert res[0]["name"] == "Lisbon Bouldering"


def test_gateway_crews_directory_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/crews/directory?city=Lisbon")
    assert resp.status_code == 200
    assert "crews" in resp.json()
