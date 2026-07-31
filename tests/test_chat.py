import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.comms import chat
from substrate.graph import Graph


def test_chat_message_sending_and_retrieval(graph: Graph):
    res_send = chat.send_message(graph, "alice", "bob", "Hey Bob! Up for climbing?")
    assert "message_id" in res_send

    msgs = chat.get_messages(graph, "bob")
    assert len(msgs) == 1
    assert msgs[0]["body"] == "Hey Bob! Up for climbing?"


def test_gateway_chat_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "sender_id": "alice",
        "recipient_id": "bob",
        "body": "How is the project going?"
    }
    resp_send = client.post("/v1/comms/messages", json=payload)
    assert resp_send.status_code == 200

    resp_get = client.get("/v1/comms/messages?recipient_id=bob")
    assert resp_get.status_code == 200
    assert len(resp_get.json()) == 1
