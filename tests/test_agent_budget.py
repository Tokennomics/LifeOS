import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.steward import budget, outbox
from substrate.graph import Graph


def test_agent_budget_and_outbox(graph: Graph):
    # Track AI tokens
    t = budget.track_tokens(graph, "steward", prompt_tokens=500, completion_tokens=200)
    assert t["total_tokens"] == 700

    b = budget.check_budget(graph, "steward", token_limit=1000)
    assert b["consumed_tokens"] == 700
    assert b["within_budget"] is True

    # Outbox
    enq = outbox.enqueue_activity(graph, "steward", "stale_task", {"task_id": "123"})
    assert enq["status"] == "pending"

    proc = outbox.process_outbox(graph)
    assert proc["processed_count"] == 1
    assert proc["activities"][0]["status"] == "executed"


def test_gateway_agent_budget_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp_b = client.get("/v1/agent/budget?module=steward")
    assert resp_b.status_code == 200
    assert "within_budget" in resp_b.json()

    resp_o = client.post("/v1/agent/outbox/process")
    assert resp_o.status_code == 200
    assert "processed_count" in resp_o.json()
