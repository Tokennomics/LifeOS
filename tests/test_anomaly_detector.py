import pytest
from fastapi.testclient import TestClient
from gateway.main import create_app
from modules.security import anomaly_detector
from substrate.graph import Graph


def test_anomaly_detection_scan(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Log critical system error
    session.create_entity(
        "admin_item",
        {
            "type": "system_log",
            "level": "ERROR",
            "module": "gateway",
            "message": "Database write failure occurred"
        },
        source="test"
    )

    # Log failed security audit attempt
    session.create_entity(
        "admin_item",
        {
            "type": "security_audit_log",
            "actor_id": "attacker_1",
            "event_type": "auth_failure",
            "details": "Unauthorized token signature attempt"
        },
        source="test"
    )

    anomalies = anomaly_detector.scan_security_anomalies(graph)
    assert len(anomalies) >= 2
    assert any(a["severity"] == "high" for a in anomalies)


def test_gateway_anomaly_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)
    resp = client.post("/v1/security/anomaly/scan")
    assert resp.status_code == 200
