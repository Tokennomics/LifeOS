import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.comms import chatroom
from substrate.graph import Graph


def test_chatroom_message_posting_and_retrieval(graph: Graph):
    msg_id = chatroom.send_message(graph, "outing_123", "alice", "Arrived at the gym")
    assert msg_id is not None

    msgs = chatroom.list_messages(graph, "outing_123")
    assert len(msgs) == 1
    assert msgs[0]["message"] == "Arrived at the gym"


def test_gateway_chatroom_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "event_id": "outing_456",
        "user_id": "bob",
        "message": "On my way"
    }
    resp_send = client.post("/v1/comms/chatroom/send", json=payload)
    assert resp_send.status_code == 200

    resp_list = client.get("/v1/comms/chatroom/list?event_id=outing_456")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1
