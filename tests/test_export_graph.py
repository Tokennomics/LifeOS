import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.backup import export_graph
from substrate.graph import Graph


def test_export_user_bundle(graph: Graph):
    session = graph.session("test", {"*"})
    session.create_entity("goal", {"title": "Exportable Goal"}, source="test")

    bundle = export_graph.export_user_bundle(graph)
    assert bundle["schema"] == "lifeos-user-export/v1"
    assert bundle["total_items"] >= 1
    assert any(i["attrs"].get("title") == "Exportable Goal" for i in bundle["items"])


def test_gateway_export_bundle_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/export/bundle")
    assert resp.status_code == 200
    assert resp.json()["schema"] == "lifeos-user-export/v1"
    assert "items" in resp.json()
