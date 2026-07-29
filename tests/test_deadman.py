import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.triage import deadman
from substrate.graph import Graph


def test_deadman_switch(graph: Graph):
    config = deadman.set_config(graph, interval_hours=1.0, grace_hours=1.0, contacts=[{"name": "Sister", "target": "+123456"}])
    assert config["enabled"] is True

    ping_res = deadman.ping(graph)
    assert ping_res["status"] == "ok"

    status = deadman.check_status(graph)
    assert status["configured"] is True
    assert status["status"] == "ok"


def test_gateway_deadman_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp_p = client.post("/v1/triage/deadman/ping")
    assert resp_p.status_code == 200
    assert resp_p.json()["status"] == "ok"

    resp_s = client.get("/v1/triage/deadman/status")
    assert resp_s.status_code == 200
    assert resp_s.json()["status"] == "ok"
