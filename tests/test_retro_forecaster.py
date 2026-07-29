import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import retro_forecaster
from substrate.graph import Graph


def test_goal_forecast_and_auto_retro(graph: Graph):
    session = graph.session("test", {"*"})
    gid = session.create_entity("goal", {"title": "Master Python 3.13"}, source="test")

    forecast = retro_forecaster.forecast_goal_completion(graph, gid)
    assert forecast["goal_id"] == gid
    assert "completion_probability" in forecast
    assert "estimated_weeks_remaining" in forecast

    retro = retro_forecaster.generate_auto_retro(graph)
    assert "headline" in retro
    assert "done_tasks_count" in retro


def test_gateway_retro_forecaster_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    graph = app.state.graph
    session = graph.session("test", {"*"})
    gid = session.create_entity("goal", {"title": "Launch Next Phase"}, source="test")

    resp_f = client.get(f"/v1/horizon/retro/forecast?goal_id={gid}")
    assert resp_f.status_code == 200
    assert resp_f.json()["goal_id"] == gid

    resp_r = client.post("/v1/horizon/retro/auto-generate")
    assert resp_r.status_code == 200
    assert "headline" in resp_r.json()
