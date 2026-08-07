"""RS256 signature verification, in pure Python, with no dependencies.

Sign-in with Google and Sign in with Apple both hand the app a JWT signed with RS256, and
the server's whole job is to check that signature. That check is the entire security of
both flows: skip it and anyone can mint a token claiming to be anyone.

**Why this is written by hand rather than pulled from PyJWT.** `cryptography` (which PyJWT
needs for RS256) does not load in the environment this was developed in, so the alternative
was to add a dependency and ship the most security-critical code in the system *untested*.
This repo has already been bitten three times by controls that were real on paper and absent
in the request path — a published signing key, a rate limiter imported by nothing, a
moderation queue with no gate. Untestable signature verification would be the fourth.

**Why hand-rolling this particular primitive is defensible**, where hand-rolling crypto
usually is not:

- **Verification uses only public values.** There is no secret, so there is no timing
  channel worth defending and no key material to leak through a sloppy implementation.
- **The historic flaw here is padding laxity** — Bleichenbacher's 2006 forgery works when an
  implementation *parses* the PKCS#1 v1.5 block and ignores trailing bytes, which lets an
  attacker with a low public exponent forge a signature without the key. This implementation
  never parses: it rebuilds the entire expected block from the digest and compares the whole
  thing, so there is nothing to be lenient about.
- `pow(sig, e, n)` is CPython's own bignum modexp, which is the only heavy arithmetic here.

If a `cryptography`-backed verifier is ever preferred, keep `verify_rs256`'s signature and
swap the body — the tests are written against the interface, not the implementation.
"""

import hashlib

#: DER prefix for a SHA-256 DigestInfo, per RFC 8017 §9.2. Constant, not parsed.
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
MIN_PADDING = 8          # RFC 8017 requires at least 8 bytes of 0xFF


def b64url_decode(value: str) -> bytes:
    """Base64url without padding, which is how every JWT field is encoded."""
    text = str(value or "")
    return __import__("base64").urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64url_uint(value: str) -> int:
    """A JWKS modulus or exponent: base64url big-endian bytes -> int."""
    return int.from_bytes(b64url_decode(value), "big")


def verify_rs256(message: bytes, signature: bytes, n: int, e: int) -> bool:
    """True if `signature` is a valid RS256 signature over `message` under (n, e).

    Never raises on malformed input — a bad signature and a corrupt one are the same
    answer, and an exception here would turn a forgery attempt into a 500.
    """
    try:
        key_bytes = (n.bit_length() + 7) // 8
        if not signature or len(signature) != key_bytes or n <= 0 or e <= 0:
            return False

        # sig^e mod n recovers the padded block the signer built.
        recovered = pow(int.from_bytes(signature, "big"), e, n).to_bytes(key_bytes, "big")

        # Rebuild what that block MUST have been, and compare all of it. No parsing.
        digest = hashlib.sha256(message).digest()
        suffix = SHA256_DIGEST_INFO + digest
        padding_len = key_bytes - len(suffix) - 3
        if padding_len < MIN_PADDING:
            return False
        expected = b"\x00\x01" + b"\xff" * padding_len + b"\x00" + suffix

        return __import__("hmac").compare_digest(recovered, expected)
    except Exception:
        return False


def verify_jwt_signature(token: str, jwk: dict) -> bool:
    """Verify a compact JWS against one JWK. Signature only — claims are checked elsewhere,
    deliberately, so neither check can be mistaken for the other."""
    try:
        header_b64, payload_b64, signature_b64 = str(token).split(".")
    except ValueError:
        return False
    if str(jwk.get("kty")) != "RSA" or str(jwk.get("alg") or "RS256") != "RS256":
        return False
    try:
        n, e = b64url_uint(jwk["n"]), b64url_uint(jwk["e"])
    except (KeyError, ValueError, TypeError):
        return False
    return verify_rs256(f"{header_b64}.{payload_b64}".encode("ascii"),
                        b64url_decode(signature_b64), n, e)
