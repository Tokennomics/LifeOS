import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.miniapp import resources
from substrate.graph import Graph


def test_resource_sharing_registry_logic(graph: Graph):
    res_reg = resources.register_resource(graph, "alice", "Climbing Rope")
    assert "resource_id" in res_reg

    res_loan = resources.request_loan(graph, res_reg["resource_id"], "bob")
    assert res_loan["status"] == "pending"


def test_gateway_resources_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload_reg = {
        "owner_id": "alice",
        "name": "Crashpad"
    }
    resp_reg = client.post("/v1/miniapp/resources", json=payload_reg)
    assert resp_reg.status_code == 200

    payload_loan = {
        "resource_id": resp_reg.json()["resource_id"],
        "borrower_id": "bob"
    }
    resp_loan = client.post("/v1/miniapp/resources/loan", json=payload_loan)
    assert resp_loan.status_code == 200
