import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import sleep_nudges
from substrate.graph import Graph


def test_sleep_nudges_calculation(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Add sleep record with low sleep duration (e.g. 5 hours)
    session.create_entity("metric", {"type": "sleep_record", "date": "2026-07-31", "hours_slept": 5.0, "sleep_quality": 4}, source="test")

    res = sleep_nudges.generate_circadian_nudge(graph)
    assert res is not None
    assert res["nudge_triggered"] is True
    assert "average sleep duration is 5.0 hours" in res["message"]


def test_gateway_sleep_nudge_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.post("/v1/routines/sleep-nudge")
    assert resp.status_code == 200
