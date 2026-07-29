import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.memento import time_capsules
from substrate.graph import Graph


def test_time_capsule_drop_and_unlock(graph: Graph):
    past_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future_iso = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()

    c1 = time_capsules.drop_time_capsule(graph, "Past memory", past_iso)
    c2 = time_capsules.drop_time_capsule(graph, "Future memory", future_iso)

    assert c1["locked"] is True
    assert c2["locked"] is True

    res = time_capsules.check_time_unlocks(graph)
    assert res["unlocked_count"] == 1
    assert res["opened"][0]["id"] == c1["capsule_id"]


def test_gateway_time_capsule_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    past_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    resp = client.post("/v1/capsules/time", json={"text": "Hello future", "unlock_at": past_iso})
    assert resp.status_code == 200
    assert resp.json()["locked"] is True

    resp_u = client.post("/v1/capsules/unlock-time")
    assert resp_u.status_code == 200
    assert resp_u.json()["unlocked_count"] >= 1
