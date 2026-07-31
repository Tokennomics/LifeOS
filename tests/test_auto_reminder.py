import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.reconnect import auto_reminder, decay
from substrate.graph import Graph


def test_enqueue_decay_reminders(graph: Graph):
    # Log a stale friend
    decay.add_person(graph, "David", cadence_days=10)
    # Tweak last_contact back in time to trigger decay
    session = graph.session("reconnect", {"people:read", "people:write"})
    people = session.find_entities("person", {"name": "David"})
    assert len(people) == 1
    p = people[0]
    p["attrs"]["last_contact"] = "2026-07-01T00:00:00Z"
    session.update_entity(p["id"], p["attrs"], source="test")

    reminders = auto_reminder.enqueue_decay_reminders(graph)
    assert len(reminders) == 1
    assert reminders[0]["name"] == "David"


def test_gateway_auto_remind_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post("/v1/reconnect/auto-remind")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
