import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.security import audit_logger
from substrate.graph import Graph


def test_audit_event_logging(graph: Graph):
    log_res = audit_logger.log_security_event(graph, "account.session_revoked", actor_id="admin_1", details={"ip": "127.0.0.1"})
    assert log_res["event_type"] == "account.session_revoked"

    logs = audit_logger.get_security_audit_log(graph)
    assert len(logs) >= 1
    assert any(l["event_type"] == "account.session_revoked" for l in logs)


def test_gateway_audit_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "event_type": "data.exported",
        "actor_id": "user_123",
        "details": {"format": "json_bundle"},
    }
    resp_l = client.post("/v1/security/audit-log", json=payload)
    assert resp_l.status_code == 200

    resp_g = client.get("/v1/security/audit-log")
    assert resp_g.status_code == 200
    assert len(resp_g.json()) >= 1
