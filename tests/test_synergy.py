import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import synergy
from substrate.graph import Graph


def test_habit_synergies(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create sleep record
    session.create_entity("metric", {"type": "sleep_record", "date": "2026-07-31", "sleep_quality": 8}, source="test")
    # Create focus session (we assume current time prefix "2026-07-31" matches)
    session.create_entity("metric", {"type": "focus_session", "duration_minutes": 60, "distraction_count": 0}, source="test")

    results = synergy.calculate_habit_synergies(graph)
    assert len(results) == 1
    # Clean check synergy score logic
    assert results[0]["habit_a"] == "High Sleep Quality (>=7)"


def test_gateway_synergy_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/routines/synergy")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
