import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.notifications import dispatcher
from substrate.graph import Graph


def test_notification_enqueue_and_dispatch(graph: Graph):
    nq = dispatcher.enqueue_notification(graph, "web_push", "user-123", "Emergency Check-in", "Please check in now")
    assert nq["status"] == "pending"

    res = dispatcher.dispatch_pending(graph)
    assert res["dispatched_count"] >= 1
    assert nq["id"] in res["dispatched_ids"]


def test_gateway_notification_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "channel": "telegram",
        "recipient": "@alice",
        "title": "Crew Invite",
        "body": "Join Lisbon Climbing Crew",
    }
    resp_e = client.post("/v1/notifications/enqueue", json=payload)
    assert resp_e.status_code == 200
    assert resp_e.json()["status"] == "pending"

    resp_d = client.post("/v1/notifications/dispatch")
    assert resp_d.status_code == 200
    assert resp_d.json()["dispatched_count"] >= 1
