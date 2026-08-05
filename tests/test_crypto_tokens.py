"""Payload signing, the happy path.

These two tests used to pass *because* of the vulnerability: the first signed with a
15-character secret, and the second relied on `sign_payload()`/`verify_payload()` sharing a
published default key. Both now use a real key from the environment. The bounds — no
default, placeholders refused, 503 rather than `valid: false` when unconfigured — live in
tests/test_security_crypto.py.
"""

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.security import crypto_tokens

KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"      # 32 chars, test-only


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)


def test_payload_signing_and_verification():
    payload = {"account_id": "acc_123", "action": "export_data"}

    sig = crypto_tokens.sign_payload(payload, secret=KEY)
    assert len(sig) == 64  # SHA256 hex digest length

    # Valid verification
    assert crypto_tokens.verify_payload(payload, sig, secret=KEY) is True

    # Tampered payload fails
    tampered_payload = {"account_id": "acc_123", "action": "delete_all"}
    assert crypto_tokens.verify_payload(tampered_payload, sig, secret=KEY) is False


def test_gateway_verify_token_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload_data = {"user": "bob", "role": "admin"}
    sig = crypto_tokens.sign_payload(payload_data)

    resp = client.post("/v1/security/verify-token", json={"data": payload_data, "signature": sig})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
