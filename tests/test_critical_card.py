import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.triage import critical_card
from substrate.graph import Graph


def test_critical_card(graph: Graph):
    data = {
        "full_name": "Bob Smith",
        "blood_type": "O+",
        "allergies": "Penicillin",
        "notes": "Emergency contacts below",
        "emergency_contacts": [{"name": "Jane Smith", "relation": "Sister", "phone": "+123456789"}],
    }

    saved = critical_card.save_critical_card(graph, data)
    assert saved["full_name"] == "Bob Smith"
    assert saved["blood_type"] == "O+"

    res = critical_card.get_critical_card(graph)
    assert res["configured"] is True
    assert res["card"]["allergies"] == "Penicillin"


def test_gateway_critical_card_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {"full_name": "Alice Green", "blood_type": "A-"}
    resp = client.post("/v1/triage/card", json=payload)
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Alice Green"

    resp_g = client.get("/v1/triage/card")
    assert resp_g.status_code == 200
    assert resp_g.json()["card"]["blood_type"] == "A-"
