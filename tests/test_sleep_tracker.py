import pytest
from fastapi.testclient import TestClient
from gateway.main import create_app
from modules.routines import sleep_tracker
from substrate.graph import Graph


def test_sleep_tracker_logging_and_summary(graph: Graph):
    # Log sleep data
    log_1 = sleep_tracker.log_sleep_data(graph, "2026-07-29", 8.5, 9, "07:30")
    assert log_1["status"] == "logged"

    log_2 = sleep_tracker.log_sleep_data(graph, "2026-07-30", 7.0, 8, "07:45")
    assert log_2["status"] == "logged"

    summary = sleep_tracker.get_circadian_summary(graph)
    assert summary["average_hours"] > 0
    assert summary["circadian_alignment_score"] > 0


def test_gateway_sleep_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "date": "2026-07-31",
        "hours_slept": 7.5,
        "sleep_quality": 8,
        "wake_time": "08:00"
    }
    resp_log = client.post("/v1/routines/sleep", json=payload)
    assert resp_log.status_code == 200

    resp_sum = client.get("/v1/routines/sleep/summary")
    assert resp_sum.status_code == 200
    assert "circadian_alignment_score" in resp_sum.json()
