import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.ledger import sync_queue
from substrate.graph import Graph


def test_ledger_sync_queue(graph: Graph):
    session = graph.session("test", {"*"})
    
    split_payload = {
        "total_amount": 100.0,
        "currency": "USD",
        "payer_id": "alice",
        "member_ids": ["alice", "bob"]
    }
    
    item_id = sync_queue.enqueue_sync_item(graph, split_payload)
    assert item_id is not None

    synced = sync_queue.process_sync_queue(graph)
    assert len(synced) == 1
    assert synced[0]["splits"][0]["amount_owed"] == 50.0


def test_gateway_sync_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "total_amount": 80.0,
        "currency": "USD",
        "payer_id": "alice",
        "member_ids": ["alice", "bob"]
    }
    resp_enq = client.post("/v1/ledger/sync-queue", json=payload)
    assert resp_enq.status_code == 200

    resp_proc = client.post("/v1/ledger/sync-queue/process")
    assert resp_proc.status_code == 200
    assert len(resp_proc.json()) == 1
