import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.security import crypto_tokens


def test_payload_signing_and_verification():
    payload = {"account_id": "acc_123", "action": "export_data"}
    secret = "test_secret_key"

    sig = crypto_tokens.sign_payload(payload, secret=secret)
    assert len(sig) == 64  # SHA256 hex digest length

    # Valid verification
    assert crypto_tokens.verify_payload(payload, sig, secret=secret) is True

    # Tampered payload fails
    tampered_payload = {"account_id": "acc_123", "action": "delete_all"}
    assert crypto_tokens.verify_payload(tampered_payload, sig, secret=secret) is False


def test_gateway_verify_token_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload_data = {"user": "bob", "role": "admin"}
    sig = crypto_tokens.sign_payload(payload_data)

    resp = client.post("/v1/security/verify-token", json={"data": payload_data, "signature": sig})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
