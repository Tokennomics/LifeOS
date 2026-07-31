import pytest
from fastapi.testclient import TestClient
from gateway.main import create_app
from modules.safety import contact_broadcast
from substrate.graph import Graph


def test_emergency_broadcast(graph: Graph):
    session = graph.session("test", {"*"})
    session.create_entity(
        "person",
        {
            "name": "Jane Doe",
            "phone": "+15559998888",
            "emergency_contact": True
        },
        source="test"
    )

    res = contact_broadcast.broadcast_emergency_alert(graph, "Help! Accident occurred.")
    assert res["status"] == "broadcast_complete"
    assert res["contacts_notified_count"] >= 1
    assert res["contacts"][0]["name"] == "Jane Doe"


def test_gateway_broadcast_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)
    resp = client.post("/v1/safety/broadcast", json={"message": "Emergency switch triggered."})
    assert resp.status_code == 200
    assert resp.json()["status"] == "broadcast_complete"
