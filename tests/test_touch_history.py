import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.reconnect import touch_history
from substrate.graph import Graph


def test_touch_history_and_notes(graph: Graph):
    session = graph.session("test", {"*"})
    person_id = session.create_entity("person", {"name": "Alice Smith", "cadence_days": 14}, source="test")
    ev_id = session.create_entity("event", {"title": "Coffee meetup", "type": "reconnect_touch"}, source="test")
    session.create_edge(ev_id, person_id, "with", source="test")

    # Fetch touch history
    history = touch_history.get_touch_history(graph, person_id)
    assert history["name"] == "Alice Smith"
    assert history["total_touches"] == 1
    assert history["history"][0]["title"] == "Coffee meetup"

    # Add context note
    res_note = touch_history.add_person_note(graph, person_id, "Met at Lisbon cafe")
    assert res_note["notes_count"] == 1


def test_gateway_touch_history_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    g = app.state.graph
    session = g.session("test", {"*"})
    pid = session.create_entity("person", {"name": "Bob Jones"}, source="test")

    resp_h = client.get(f"/v1/reconnect/history/{pid}")
    assert resp_h.status_code == 200
    assert resp_h.json()["name"] == "Bob Jones"

    resp_n = client.post("/v1/reconnect/notes", json={"person_id": pid, "note": "Wants to collaborate on LifeOS"})
    assert resp_n.status_code == 200
    assert resp_n.json()["notes_count"] == 1
