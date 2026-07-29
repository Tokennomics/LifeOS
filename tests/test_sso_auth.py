import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.accounts import sso_auth
from substrate.graph import Graph


def test_sso_authentication_and_linking(graph: Graph):
    providers = sso_auth.get_supported_providers()
    assert "google" in providers
    assert "apple" in providers
    assert "phone" in providers
    assert "email" in providers

    auth_res = sso_auth.authenticate_sso(graph, "google", "google_12345", email="alice@example.com", name="Alice")
    assert auth_res["is_new"] is True
    aid = auth_res["account_id"]

    link_res = sso_auth.link_identity_provider(graph, aid, "apple", "apple_9999")
    assert "apple" in link_res["linked_providers"]


def test_gateway_sso_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp_p = client.get("/v1/auth/providers")
    assert resp_p.status_code == 200
    assert "google" in resp_p.json()

    payload_l = {
        "provider": "email",
        "provider_user_id": "email_user_1",
        "email": "bob@example.com",
        "name": "Bob",
    }
    resp_l = client.post("/v1/auth/sso/login", json=payload_l)
    assert resp_l.status_code == 200
    aid = resp_l.json()["account_id"]

    resp_lk = client.post("/v1/auth/sso/link", json={"account_id": aid, "provider": "phone", "provider_user_id": "+15551234567"})
    assert resp_lk.status_code == 200
    assert "phone" in resp_lk.json()["linked_providers"]
