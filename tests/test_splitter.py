import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.ledger import splitter
from substrate.graph import Graph


def test_expense_splitting(graph: Graph):
    res = splitter.split_expenses(
        graph,
        total_amount=120.0,
        currency="EUR",
        payer_id="alice",
        member_ids=["bob", "charlie"]
    )
    assert res["total_amount"] == 120.0
    assert res["individual_share"] == 40.0
    assert len(res["splits"]) == 2
    assert res["splits"][0]["from_member_id"] in ("bob", "charlie")
    assert res["splits"][0]["amount_owed"] == 40.0


def test_gateway_split_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "total_amount": 90.0,
        "currency": "USD",
        "payer_id": "alice",
        "member_ids": ["bob", "charlie"]
    }
    resp = client.post("/v1/ledger/split", json=payload)
    assert resp.status_code == 200
    assert resp.json()["individual_share"] == 30.0
