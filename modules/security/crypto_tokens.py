"""Cryptographic Payload Signer & Token Integrity Core.

Generates HMAC-SHA256 signatures for request payloads and verifies token integrity
to prevent replay attacks, token tampering, and unauthorized data forgery.

**The key comes from the environment and there is no default.**

There used to be one — `secret: str = "lifeos_secret_key_2026"` — and the gateway called
`verify_payload()` without overriding it. A signing key with a published default is not a
signing key: anyone who can read the repository can mint a valid signature for any payload,
which is precisely the forgery this module exists to prevent. It is the mirror image of the
standing "no secrets in the repo" rule — nothing real leaked out, but a fake key was being
trusted as though it were real.

So: `LIFEOS_SIGNING_KEY` (or `signing.key` in config) is required, and a missing or
obviously-placeholder key raises rather than quietly signing with something guessable.
Failing loudly at the first call is the only safe behaviour; falling back to a default is
how you end up believing you have integrity checking when you have decoration.

Generate one with:
    python3 -c "import secrets; print(secrets.token_urlsafe(32))"
"""

import hashlib
import hmac
import json
import os

ENV_VAR = "LIFEOS_SIGNING_KEY"
MIN_KEY_LENGTH = 32

# Keys that have appeared in this repo or are otherwise public. Refused by name so that
# copying an old value out of git history can't silently restore the hole.
_KNOWN_PUBLIC = {
    "lifeos_secret_key_2026",
    "changeme", "secret", "password", "test", "dev",
}


class SigningKeyError(RuntimeError):
    """Raised when no usable signing key is configured."""


def _resolve(secret: str | None) -> str:
    """The key to sign with: an explicit argument, else the environment. Never a default."""
    key = secret if secret is not None else os.environ.get(ENV_VAR, "")
    key = str(key or "").strip()
    if not key:
        raise SigningKeyError(
            f"{ENV_VAR} is not set. Payload signing has no default key — generate one with "
            f'python3 -c "import secrets; print(secrets.token_urlsafe(32))" and set it in the '
            f"environment (see deploy/vps/.env.example)."
        )
    if key.lower() in _KNOWN_PUBLIC:
        raise SigningKeyError(
            f"{ENV_VAR} is set to a known placeholder value. That key is public — it signs "
            f"nothing. Generate a real one."
        )
    if len(key) < MIN_KEY_LENGTH:
        raise SigningKeyError(
            f"{ENV_VAR} must be at least {MIN_KEY_LENGTH} characters; got {len(key)}."
        )
    return key


def signing_configured() -> bool:
    """Whether a usable key exists — for a health check or a startup warning.

    Deliberately does not say *why* it's unusable; callers that need the reason should let
    `_resolve` raise and read the message.
    """
    try:
        _resolve(None)
        return True
    except SigningKeyError:
        return False


def sign_payload(data: dict, secret: str | None = None) -> str:
    """Generate an HMAC-SHA256 signature for a JSON payload."""
    if not isinstance(data, dict):
        raise ValueError("data must be a dict")
    key = _resolve(secret)
    serialized = json.dumps(data, sort_keys=True).encode("utf-8")
    return hmac.new(key.encode("utf-8"), serialized, hashlib.sha256).hexdigest()


def verify_payload(data: dict, signature: str, secret: str | None = None) -> bool:
    """Verify an HMAC-SHA256 signature against a JSON payload.

    A malformed signature is False, but a MISSING KEY raises: "the signature didn't match"
    and "we cannot check signatures at all" are different facts, and collapsing the second
    into the first is how a broken deployment starts reporting clean verifications.
    """
    key = _resolve(secret)
    if not signature or not isinstance(signature, str):
        return False
    expected = sign_payload(data, secret=key)
    return hmac.compare_digest(expected.lower().strip(), signature.lower().strip())
