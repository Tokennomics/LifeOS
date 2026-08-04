import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.ledger import payments
from substrate.graph import Graph


def test_payment_settlements_and_balance_compiles(graph: Graph):
    pay_id = payments.record_payment(graph, "alice", "bob", 35.0, "USD")
    assert pay_id is not None

    bals = payments.calculate_balances(graph)
    assert bals["net_balances"]["alice"] == 35.0
    assert bals["net_balances"]["bob"] == -35.0


def test_gateway_payments_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "payer_id": "alice",
        "payee_id": "bob",
        "amount": 20.0,
        "currency": "USD"
    }
    resp_rec = client.post("/v1/ledger/payments", json=payload)
    assert resp_rec.status_code == 200

    resp_bal = client.get("/v1/ledger/payments/balances")
    assert resp_bal.status_code == 200
    assert resp_bal.json()["net_balances"]["alice"] == 20.0
