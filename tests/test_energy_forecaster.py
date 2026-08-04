import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.vitals import energy_forecaster
from substrate.graph import Graph


def test_sleep_battery_forecasting(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Baseline check
    res_base = energy_forecaster.forecast_energy_battery(graph)
    assert res_base["predicted_body_battery"] == 75

    # Create sleep record
    session.create_entity("metric", {"type": "sleep_record", "hours_slept": 8.0, "sleep_quality": 9}, source="test")
    res_forecast = energy_forecaster.forecast_energy_battery(graph)
    assert res_forecast["predicted_body_battery"] == 90


def test_gateway_energy_forecast_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/vitals/energy-forecast")
    assert resp.status_code == 200
    assert "predicted_body_battery" in resp.json()
