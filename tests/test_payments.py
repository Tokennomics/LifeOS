import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.billing import payments
from substrate.graph import Graph


def test_billing_customer_and_subscription(graph: Graph):
    session = graph.session("test", {"*"})
    aid = session.create_entity("person", {"name": "Subscriber"}, source="test")

    cust_res = payments.create_customer(graph, aid, "sub@example.com")
    assert cust_res["plan"] == "free"
    assert cust_res["stripe_customer_id"] != ""

    sub_res = payments.subscribe_plan(graph, aid, "pro")
    assert sub_res["plan"] == "pro"
    assert sub_res["subscription_status"] == "active"

    status = payments.get_billing_status(graph, aid)
    assert status["plan"] == "pro"


def test_gateway_billing_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    graph = app.state.graph
    session = graph.session("test", {"*"})
    aid = session.create_entity("person", {"name": "API Billing User"}, source="test")

    resp_c = client.post("/v1/billing/customer", json={"account_id": aid, "email": "api@example.com"})
    assert resp_c.status_code == 200

    resp_s = client.post("/v1/billing/subscribe", json={"account_id": aid, "plan_id": "team"})
    assert resp_s.status_code == 200
    assert resp_s.json()["plan"] == "team"

    resp_st = client.get(f"/v1/billing/status?account_id={aid}")
    assert resp_st.status_code == 200
    assert resp_st.json()["plan"] == "team"
