import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import tracker
from substrate.graph import Graph


def test_routine_creation_and_completion(graph: Graph):
    routine_res = tracker.create_routine(graph, "Morning Hydration", trigger="Waking up", time_of_day="morning", items=["Drink 500ml water"])
    rid = routine_res["routine_id"]
    assert routine_res["streak"] == 0

    comp_res = tracker.log_routine_completion(graph, rid)
    assert comp_res["streak"] == 1
    assert comp_res["last_completed"] != ""

    statuses = tracker.get_routines_status(graph)
    assert len(statuses) >= 1
    assert any(s["routine_id"] == rid and s["streak"] == 1 for s in statuses)


def test_gateway_routine_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "name": "Evening Review",
        "trigger": "After dinner",
        "time_of_day": "evening",
        "items": ["Review Triage Briefing"],
    }
    resp_c = client.post("/v1/routines", json=payload)
    assert resp_c.status_code == 200
    rid = resp_c.json()["routine_id"]

    resp_log = client.post(f"/v1/routines/{rid}/complete")
    assert resp_log.status_code == 200
    assert resp_log.json()["streak"] == 1

    resp_s = client.get("/v1/routines/streaks")
    assert resp_s.status_code == 200
    assert len(resp_s.json()) >= 1
