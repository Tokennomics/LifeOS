import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.backup import export_graph, import_graph
from substrate.graph import Graph


def test_bundle_restore(graph: Graph):
    # First export
    bundle = export_graph.export_user_bundle(graph)

    # Now restore into graph
    res = import_graph.restore_user_bundle(graph, bundle)
    assert res["status"] == "restored"
    assert "restored_entities_count" in res


def test_gateway_restore_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    # Get export
    resp_e = client.get("/v1/export/bundle")
    assert resp_e.status_code == 200
    bundle = resp_e.json()

    # Post restore
    resp_r = client.post("/v1/export/restore", json={"bundle_data": bundle})
    assert resp_r.status_code == 200
    assert resp_r.json()["status"] == "restored"
