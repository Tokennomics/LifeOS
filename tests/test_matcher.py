import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import matcher
from substrate.graph import Graph


def test_schedule_availability_matching(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create calendar event
    session.create_entity("metric", {"type": "calendar_event", "owner_id": "alice", "date": "2026-08-04", "time_slot": "10:00"}, source="test")

    slots = matcher.match_outing_slots(graph, ["alice", "bob"], "2026-08-04")
    assert "10:00" not in slots
    assert "18:00" in slots


def test_gateway_matcher_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "member_ids": ["alice"],
        "day": "2026-08-04"
    }
    resp = client.post("/v1/venues/match-outing", json=payload)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
