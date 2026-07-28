import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.steward import actions, scanners
from substrate.graph import Graph


def test_steward_missing_retro_scanner(graph: Graph):
    session = graph.session("test", {"*"})
    # Create past task in week 2026-W01
    session.create_entity("task", {"title": "Past task", "status": "open", "week": "2026-W01"}, source="test")

    res = scanners.scan(graph)
    assert res["created"] > 0

    open_items = actions.open_items(graph)
    missing_retro_item = next((i for i in open_items if i["type"] == "missing_retro"), None)
    assert missing_retro_item is not None
    assert "2026-W01" in missing_retro_item["title"]


def test_gateway_steward_queue_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/steward/queue")
    assert resp.status_code == 200
    assert "items" in resp.json()
