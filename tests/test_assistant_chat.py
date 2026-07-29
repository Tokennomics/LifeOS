import pytest
from fastapi.testclient import TestClient

from gateway import assistant_chat
from gateway.main import create_app
from substrate.graph import Graph


def test_assistant_chat_processing(graph: Graph):
    res = assistant_chat.process_assistant_message(graph, "What is my top priority today?")
    assert "reply" in res
    assert "context_summary" in res


def test_gateway_assistant_chat_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {"message": "How is my energy level looking?"}
    resp = client.post("/v1/assistant/chat", json=payload)
    assert resp.status_code == 200
    assert "reply" in resp.json()
