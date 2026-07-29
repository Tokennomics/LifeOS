import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.platform import manifest
from substrate.graph import Graph


def test_manifest_validation_and_session(graph: Graph):
    manifest_data = {
        "name": "custom_analytics",
        "version": "1.0.0",
        "scopes": ["goals:read", "tasks:read"],
        "token_budget": 50000,
    }

    val = manifest.validate_manifest(manifest_data)
    assert val["valid"] is True
    assert val["name"] == "custom_analytics"

    sess = manifest.create_manifest_session(graph, manifest_data)
    assert sess.module == "custom_analytics"
    assert "goals:read" in sess.scopes


def test_gateway_manifest_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "manifest": {
            "name": "bot_plugin",
            "version": "0.1.0",
            "scopes": ["content:read"],
        }
    }
    resp = client.post("/v1/platform/validate", json=payload)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
