import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import qa_bot
from substrate.graph import Graph


def test_memory_qa_bot_search(graph: Graph):
    session = graph.session("test", {"*"})
    
    session.create_entity("memory", {"title": "Summer Outing", "text": "Had fresh grilled salmon with team Alice"}, source="test")
    session.create_entity("memory", {"title": "Skiing Trip", "text": "Learned deep snow carving"}, source="test")

    res = qa_bot.query_graph_memories(graph, "What did we eat during the summer?")
    assert len(res) >= 1
    assert "salmon" in res[0]["text"]


def test_gateway_qa_bot_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {"query_text": "salmon"}
    resp = client.post("/v1/graph/qa", json=payload)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
