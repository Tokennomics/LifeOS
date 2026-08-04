import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import consistency
from substrate.graph import Graph


def test_consistency_trend_forecasting(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Baseline checks (empty)
    res_base = consistency.forecast_consistency(graph)
    assert res_base["current_consistency_percentage"] == 75.0
    assert res_base["forecasted_30d_consistency"] == 78.0

    # Seed task record
    session.create_entity("admin_item", {"type": "routine_streak", "completed_today": True}, source="test")
    res_completed = consistency.forecast_consistency(graph)
    assert res_completed["current_consistency_percentage"] == 100.0


def test_gateway_consistency_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/routines/consistency-forecast")
    assert resp.status_code == 200
    assert "current_consistency_percentage" in resp.json()
