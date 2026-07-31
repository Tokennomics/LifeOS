import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import mindfulness
from substrate.graph import Graph


def test_mindfulness_logging_and_summary(graph: Graph):
    # Log focus sessions
    res_1 = mindfulness.log_focus_session(graph, 30, 2, "Read research papers")
    assert "session_id" in res_1
    assert res_1["wellness_score"] == 10.0

    res_2 = mindfulness.log_focus_session(graph, 45, 0, "Deep coding session")
    assert res_2["wellness_score"] == 45.0

    summary = mindfulness.get_mindfulness_summary(graph)
    assert summary["total_sessions"] == 2
    assert summary["average_duration_minutes"] == 37.5
    assert summary["average_distractions"] == 1.0


def test_gateway_mindfulness_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    # Log session via API
    payload = {
        "duration_minutes": 25,
        "distraction_count": 1,
        "note": "Focused writing"
    }
    resp_log = client.post("/v1/routines/mindfulness/session", json=payload)
    assert resp_log.status_code == 200
    assert "session_id" in resp_log.json()

    # Get summary via API
    resp_sum = client.get("/v1/routines/mindfulness/summary")
    assert resp_sum.status_code == 200
    assert resp_sum.json()["total_sessions"] == 1
