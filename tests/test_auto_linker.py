import pytest
from fastapi.testclient import TestClient
from gateway.main import create_app
from modules.vault import auto_linker
from substrate.graph import Graph


def test_auto_linker_matching(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create two notes sharing tags: "health" and "fitness"
    session.create_entity(
        "memory",
        {
            "title": "Note A",
            "tags": ["health", "fitness", "diet"]
        },
        source="test"
    )
    session.create_entity(
        "memory",
        {
            "title": "Note B",
            "tags": ["health", "fitness", "sleep"]
        },
        source="test"
    )

    res = auto_linker.auto_link_notes(graph)
    assert res["edges_created"] >= 1


def test_gateway_auto_link_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)
    resp = client.post("/v1/vault/auto-link")
    assert resp.status_code == 200
    assert "edges_created" in resp.json()
