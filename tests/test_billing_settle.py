import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.ledger import billing
from substrate.graph import Graph


def test_split_settlement(graph: Graph):
    res = billing.settle_split(graph, "split_abc", 40.0)
    assert res["split_id"] == "split_abc"
    assert res["status"] == "success"


def test_gateway_settle_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "split_id": "split_xyz",
        "settled_amount": 30.0
    }
    resp = client.post("/v1/ledger/settle", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
