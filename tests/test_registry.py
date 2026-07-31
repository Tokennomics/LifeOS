import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.miniapp import registry
from substrate.graph import Graph


def test_miniapp_registration_and_listing(graph: Graph):
    res_reg = registry.register_miniapp(graph, "Splitting Pro", "https://split.lifeos.local/app", "split_icon")
    assert "app_id" in res_reg

    apps = registry.list_miniapps(graph)
    assert len(apps) == 1
    assert apps[0]["name"] == "Splitting Pro"


def test_gateway_registry_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "name": "Gym Routine Tracker",
        "url": "https://gym.lifeos.local/app",
        "icon": "gym_icon"
    }
    resp_reg = client.post("/v1/miniapp/register", json=payload)
    assert resp_reg.status_code == 200

    resp_list = client.get("/v1/miniapp/list")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1
