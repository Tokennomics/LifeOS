import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.growth import feedback
from substrate.graph import Graph


def test_event_feedback_and_crew_activation(graph: Graph):
    crew_id = "crew-lisbon-climb"

    # Event 1
    feedback.record_event_feedback(graph, crew_id, "event-1", rating=5, notes="Great turnout!")
    status1 = feedback.crew_activation_status(graph, crew_id)
    assert status1["meet_count"] == 1
    assert status1["is_activated"] is False
    assert status1["status"] == "onboarding"

    # Event 2
    feedback.record_event_feedback(graph, crew_id, "event-2", rating=4, notes="Second meetup")
    status2 = feedback.crew_activation_status(graph, crew_id)
    assert status2["meet_count"] == 2
    assert status2["is_activated"] is True
    assert status2["status"] == "activated"
    assert status2["average_rating"] == 4.5


def test_gateway_growth_feedback_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    crew_id = "crew-test"
    resp_f = client.post(f"/v1/crews/{crew_id}/feedback", json={"event_id": "e1", "rating": 5})
    assert resp_f.status_code == 200
    assert resp_f.json()["rating"] == 5

    resp_a = client.get(f"/v1/crews/{crew_id}/activation")
    assert resp_a.status_code == 200
    assert resp_a.json()["meet_count"] == 1
