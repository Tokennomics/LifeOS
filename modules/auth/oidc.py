"""Sign in with Google / Apple — verifying the ID token they hand the app.

The app does the interactive part with the platform SDK and sends the resulting ID token
here. This module decides whether to believe it. Everything below is a check that has been
skipped in a real breach somewhere, which is why each one is spelled out rather than folded
into a library call.

**Signature, then claims, in that order and never merged.** `rs256.verify_jwt_signature`
answers "did the provider sign this"; the claim checks answer "did they sign it *for us,
recently, about a verified person*". A token can be perfectly signed by Google and still be
worthless to us — it might be minted for a *different app*, which is the `aud` check, and is
exactly how "sign in with Google" becomes "sign in as anyone" if you skip it.

**`email_verified` is load-bearing.** An unverified email from a provider is a claim the
user typed, not one the provider stands behind. Accepting it would let someone register
`victim@gmail.com` at a sloppy IdP and walk into the victim's account. If the provider does
not assert the email is verified, the email is dropped and only the opaque `sub` is used.

**`alg` is never read from the token.** The header is attacker-controlled; honouring it is
how `alg: none` and the HMAC-with-RSA-public-key confusion both work. RS256 is assumed
because that is what both providers issue.

The JWKS fetch is injectable and goes through `substrate.safefetch`, so the network is not a
precondition for testing this — the same door feeds and Tier 2 providers use.
"""

import datetime
import json
import os

from modules.auth import rs256

LEEWAY_SECONDS = 120       # clock skew between a phone and a server

PROVIDERS = {
    "google": {
        "issuers": ("https://accounts.google.com", "accounts.google.com"),
        "jwks": "https://www.googleapis.com/oauth2/v3/certs",
        "env": "LIFEOS_GOOGLE_CLIENT_ID",
    },
    "apple": {
        "issuers": ("https://appleid.apple.com",),
        "jwks": "https://appleid.apple.com/auth/keys",
        "env": "LIFEOS_APPLE_CLIENT_ID",
    },
}


class TokenRejected(ValueError):
    """The token is not one we can act on. The message says which check failed."""


def configured(provider: str) -> bool:
    spec = PROVIDERS.get(provider)
    return bool(spec and str(os.environ.get(spec["env"], "")).strip())


def status() -> list[dict]:
    """Which sign-in providers are switched on. Never returns a client id."""
    return [{"provider": name, "configured": configured(name), "env_var": spec["env"]}
            for name, spec in sorted(PROVIDERS.items())]


def _now() -> int:
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


def _segments(token: str) -> tuple[dict, dict]:
    try:
        header_b64, payload_b64, _ = str(token).split(".")
        header = json.loads(rs256.b64url_decode(header_b64))
        claims = json.loads(rs256.b64url_decode(payload_b64))
    except Exception:
        raise TokenRejected("not a well-formed JWT")
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise TokenRejected("not a well-formed JWT")
    return header, claims


def fetch_jwks(provider: str) -> dict:
    from substrate import safefetch
    return json.loads(safefetch.fetch_text(PROVIDERS[provider]["jwks"]))


def verify_id_token(provider: str, token: str, *, jwks: dict | None = None,
                    nonce: str | None = None, now: int | None = None) -> dict:
    """Verify an ID token and return the identity it proves. Raises `TokenRejected`."""
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise TokenRejected(f"unknown provider {provider!r}")
    audience = str(os.environ.get(spec["env"], "")).strip()
    if not audience:
        raise TokenRejected(f"{spec['env']} is not set; {provider} sign-in is off")

    header, claims = _segments(token)
    keys = (jwks or fetch_jwks(provider)).get("keys") or []
    kid = header.get("kid")
    # Match on kid when the token names one; otherwise try every key. Never trust `alg`.
    candidates = [k for k in keys if not kid or k.get("kid") == kid] or keys
    if not any(rs256.verify_jwt_signature(token, k) for k in candidates):
        raise TokenRejected("signature does not verify against the provider's keys")

    if claims.get("iss") not in spec["issuers"]:
        raise TokenRejected(f"wrong issuer: {claims.get('iss')!r}")

    aud = claims.get("aud")
    aud_list = aud if isinstance(aud, list) else [aud]
    if audience not in [str(a) for a in aud_list]:
        raise TokenRejected("token was issued for a different application")

    stamp = now if now is not None else _now()
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, (int, float)) or stamp > exp + LEEWAY_SECONDS:
        raise TokenRejected("token has expired")
    if isinstance(iat, (int, float)) and iat - LEEWAY_SECONDS > stamp:
        raise TokenRejected("token is issued in the future")

    if nonce is not None and str(claims.get("nonce") or "") != str(nonce):
        raise TokenRejected("nonce does not match")

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise TokenRejected("token carries no subject")

    # An unverified email is something the user typed, not something the provider stands
    # behind. Dropping it is what stops "register victim@gmail.com at a sloppy IdP".
    verified = claims.get("email_verified")
    verified = verified is True or str(verified).lower() == "true"
    email = str(claims.get("email") or "").strip().lower() if verified else ""

    return {"provider": provider, "subject": subject, "email": email,
            "email_verified": bool(email), "name": str(claims.get("name") or "")[:80]}
