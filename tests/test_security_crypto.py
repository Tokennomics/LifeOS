"""Payload signing — the key must come from the environment, and never from the repo.

`crypto_tokens` shipped with `secret: str = "lifeos_secret_key_2026"` as a default, and the
gateway called `verify_payload()` without overriding it. A signing key with a published
default is not a signing key: anyone who can read the repository can mint a valid signature.
These tests exist so that hole cannot be reopened by a well-meaning "add a fallback so the
tests pass" change — the fallback IS the vulnerability.
"""

import os

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.security import crypto_tokens

REAL_KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"      # 32 chars, test-only
PAYLOAD = {"account": "ana", "amount": 10, "nested": {"b": 2, "a": 1}}


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, REAL_KEY)
    return REAL_KEY


@pytest.fixture
def unkeyed(monkeypatch):
    monkeypatch.delenv(crypto_tokens.ENV_VAR, raising=False)


# ---- the hole that was here -------------------------------------------------

def test_no_key_means_no_signing_rather_than_a_guessable_one(unkeyed):
    """The old default let anyone with the repo forge a signature. There is no default now."""
    with pytest.raises(crypto_tokens.SigningKeyError):
        crypto_tokens.sign_payload(PAYLOAD)
    with pytest.raises(crypto_tokens.SigningKeyError):
        crypto_tokens.verify_payload(PAYLOAD, "any-signature")


def test_the_old_published_key_is_refused_by_name(monkeypatch):
    """Copying it back out of git history must not restore the hole."""
    monkeypatch.setenv(crypto_tokens.ENV_VAR, "lifeos_secret_key_2026")
    with pytest.raises(crypto_tokens.SigningKeyError, match="placeholder"):
        crypto_tokens.sign_payload(PAYLOAD)


@pytest.mark.parametrize("weak", ["changeme", "secret", "password", "test", "dev"])
def test_other_obvious_placeholders_are_refused(monkeypatch, weak):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, weak)
    with pytest.raises(crypto_tokens.SigningKeyError):
        crypto_tokens.sign_payload(PAYLOAD)


def test_a_short_key_is_refused(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, "x" * (crypto_tokens.MIN_KEY_LENGTH - 1))
    with pytest.raises(crypto_tokens.SigningKeyError, match="at least"):
        crypto_tokens.sign_payload(PAYLOAD)


def test_whitespace_is_not_a_key(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, "   ")
    with pytest.raises(crypto_tokens.SigningKeyError):
        crypto_tokens.sign_payload(PAYLOAD)


# ---- it still does its job --------------------------------------------------

def test_a_signature_round_trips(keyed):
    sig = crypto_tokens.sign_payload(PAYLOAD)
    assert crypto_tokens.verify_payload(PAYLOAD, sig) is True


def test_key_order_does_not_change_the_signature(keyed):
    a = crypto_tokens.sign_payload({"a": 1, "b": 2})
    b = crypto_tokens.sign_payload({"b": 2, "a": 1})
    assert a == b, "serialization must be deterministic or verification is a coin flip"


def test_a_tampered_payload_fails(keyed):
    sig = crypto_tokens.sign_payload(PAYLOAD)
    assert crypto_tokens.verify_payload({**PAYLOAD, "amount": 1000}, sig) is False


def test_a_signature_from_a_different_key_fails(keyed):
    forged = crypto_tokens.sign_payload(PAYLOAD, secret="Zt4Kw8Lm2QpXv6Nr9Bc3JsHy5Ff7Gd1A")
    assert crypto_tokens.verify_payload(PAYLOAD, forged) is False


def test_an_empty_or_malformed_signature_is_false_not_an_error(keyed):
    for bad in ("", None, 12345, "not-hex"):
        assert crypto_tokens.verify_payload(PAYLOAD, bad) is False


def test_signing_configured_reports_the_truth(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, REAL_KEY)
    assert crypto_tokens.signing_configured() is True
    monkeypatch.delenv(crypto_tokens.ENV_VAR, raising=False)
    assert crypto_tokens.signing_configured() is False


# ---- the gateway ------------------------------------------------------------

def test_gateway_verifies_a_real_signature(cfg, keyed):
    client = TestClient(create_app(cfg))
    sig = crypto_tokens.sign_payload(PAYLOAD)
    r = client.post("/v1/security/verify-token", json={"data": PAYLOAD, "signature": sig})
    assert r.status_code == 200 and r.json()["valid"] is True


def test_gateway_rejects_a_forged_signature(cfg, keyed):
    client = TestClient(create_app(cfg))
    r = client.post("/v1/security/verify-token",
                    json={"data": PAYLOAD, "signature": "deadbeef" * 8})
    assert r.status_code == 200 and r.json()["valid"] is False


def test_gateway_says_503_not_false_when_it_cannot_check(cfg, unkeyed):
    """`valid: false` reads as 'checked and rejected'. Unconfigured is a different fact, and
    reporting it as a rejection is how a broken deployment looks like a working one."""
    client = TestClient(create_app(cfg))
    r = client.post("/v1/security/verify-token", json={"data": PAYLOAD, "signature": "abc"})
    assert r.status_code == 503
    assert crypto_tokens.ENV_VAR in r.json()["detail"]
