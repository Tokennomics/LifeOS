import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import habits_rec
from substrate.graph import Graph


def test_vital_habits_recommender(graph: Graph):
    # Baseline checks
    rec = habits_rec.recommend_vital_habit(graph, 37.7749, -122.4194)
    assert rec["habit_title"] == "Stretch & Hydrate"

    # Seed stress levels
    session = graph.session("test", {"*"})
    session.create_entity("metric", {"type": "stress_level", "value": 85}, source="test")

    rec_stress = habits_rec.recommend_vital_habit(graph, 37.7749, -122.4194)
    assert rec_stress["habit_title"] == "Box Breathing"


def test_gateway_habits_rec_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "latitude": 37.7749,
        "longitude": -122.4194
    }
    resp = client.post("/v1/routines/activity-recommendation", json=payload)
    assert resp.status_code == 200
    assert "habit_title" in resp.json()
