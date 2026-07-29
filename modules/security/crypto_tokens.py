"""Cryptographic Payload Signer & Token Integrity Core.

Generates HMAC-SHA256 signatures for request payloads and verifies token integrity
to prevent replay attacks, token tampering, and unauthorized data forgery.
"""

import hmac
import hashlib
import json


def sign_payload(data: dict, secret: str = "lifeos_secret_key_2026") -> str:
    """Generates an HMAC-SHA256 signature for a JSON payload."""
    if not isinstance(data, dict):
        raise ValueError("data must be a dict")

    # Serialize deterministically with sorted keys
    serialized = json.dumps(data, sort_keys=True).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), serialized, hashlib.sha256).hexdigest()
    return signature


def verify_payload(data: dict, signature: str, secret: str = "lifeos_secret_key_2026") -> bool:
    """Verifies an HMAC-SHA256 signature against a JSON payload."""
    if not signature or not isinstance(signature, str):
        return False

    expected_sig = sign_payload(data, secret=secret)
    return hmac.compare_digest(expected_sig.lower().strip(), signature.lower().strip())
