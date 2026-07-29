import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.telemetry import system_logger
from substrate.graph import Graph


def test_system_event_logging(graph: Graph):
    log_res = system_logger.log_system_event(graph, "ERROR", "billing", "Payment webhook timeout", {"attempt": 3})
    assert log_res["level"] == "ERROR"

    logs = system_logger.get_system_logs(graph, level="ERROR")
    assert len(logs) >= 1
    assert any(l["message"] == "Payment webhook timeout" for l in logs)


def test_gateway_system_logger_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "level": "INFO",
        "module": "gateway",
        "message": "Gateway route initialized",
        "metadata": {"route": "/v1/auth/sso/login"},
    }
    resp_l = client.post("/v1/system/log", json=payload)
    assert resp_l.status_code == 200

    resp_g = client.get("/v1/system/logs?level=INFO")
    assert resp_g.status_code == 200
    assert len(resp_g.json()) >= 1
