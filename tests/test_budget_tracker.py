import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.finance import budget_tracker
from substrate.graph import Graph


def test_financial_goal_tracking(graph: Graph):
    goal_res = budget_tracker.create_financial_goal(graph, "6-Month Runway", target_amount=30000.0, current_amount=10000.0)
    gid = goal_res["financial_goal_id"]
    assert goal_res["completion_percentage"] == 33.3

    prog_res = budget_tracker.log_financial_progress(graph, gid, amount_delta=5000.0)
    assert prog_res["current_amount"] == 15000.0
    assert prog_res["completion_percentage"] == 50.0

    summary = budget_tracker.get_financial_summary(graph)
    assert summary["financial_goals_count"] >= 1
    assert summary["total_current_amount"] >= 15000.0


def test_gateway_financial_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload_c = {
        "title": "Lisbon Travel Budget",
        "target_amount": 2000.0,
        "current_amount": 500.0,
        "currency": "EUR",
    }
    resp_c = client.post("/v1/finance/goals", json=payload_c)
    assert resp_c.status_code == 200
    gid = resp_c.json()["financial_goal_id"]

    resp_p = client.post(f"/v1/finance/goals/{gid}/progress", json={"amount_delta": 500.0})
    assert resp_p.status_code == 200
    assert resp_p.json()["current_amount"] == 1000.0

    resp_s = client.get("/v1/finance/summary")
    assert resp_s.status_code == 200
    assert resp_s.json()["financial_goals_count"] >= 1
