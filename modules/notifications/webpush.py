"""Web Push — the one way this app can reach a phone that is not looking at it.

Until now every "notify" in LifeOS was honest about not happening: `push_delivered: False`
on every response, because there was "no VAPID key pair anywhere in the repo". This module
is that key pair and the two protocols behind it, written against the standards rather than
a wrapper library (the usual one ships source-only and did not build here):

- **VAPID** (RFC 8292). The server signs a short ES256 JWT naming the push service it is
  talking to, so the service knows which application server a subscription belongs to.
- **Message encryption** (RFC 8291, `aes128gcm` from RFC 8188). The push service relays
  the payload and cannot read it: it is encrypted to the browser's own key.

The key pair is **generated on first use and kept in the database**, or taken from
`LIFEOS_VAPID_PRIVATE_KEY` if set. An owner deploying from a phone cannot run a key
generator, and a Render `generateValue` is a random string, not a P-256 key. The private
key never leaves the server; the public half is what the browser subscribes with.

What "delivered" means here is exactly what the push service says: `push_delivered` is true
only when the service accepted the message (201/202). A 404/410 means the browser dropped
the subscription, so the row is deleted rather than retried forever.

Endpoints are browser-chosen URLs, so they are held to an allowlist of the push services
browsers actually use, over https, through the same SSRF check as every other fetch. A
subscription pointing anywhere else is refused at subscribe time and again at send time.
"""

import base64
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "notifications.webpush"
SCOPES = {"content:read", "content:write"}
KEY_RECORD = "vapid_key"
SUB_RECORD = "push_subscription"
KEY_VAR = "LIFEOS_VAPID_PRIVATE_KEY"
SUBJECT_VAR = "LIFEOS_VAPID_SUBJECT"
TTL_SECONDS = 12 * 3600
RECORD_SIZE = 4096
MAX_SUBS_PER_OWNER = 10
MAX_PAYLOAD = 3000

# The push services browsers use. Chrome/Edge/Android: FCM. Firefox: Mozilla autopush.
# Safari (macOS and iOS 16.4+ home-screen apps): Apple. Windows: WNS.
PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com",
              "updates.push.services.mozilla.com", "push.services.mozilla.com",
              "web.push.apple.com", "notify.windows.com")


class PushError(ValueError):
    """A subscription or message that cannot be accepted."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    text = str(text or "")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


# ---- keys ------------------------------------------------------------------------

def _ec():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec


def _private_from_d(d: bytes):
    ec = _ec()
    return ec.derive_private_key(int.from_bytes(d, "big"), ec.SECP256R1())


def _raw_public(key) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return key.public_key().public_bytes(serialization.Encoding.X962,
                                         serialization.PublicFormat.UncompressedPoint)


def _server_key(graph: Graph):
    """The application server's P-256 key: env first, then the stored one, else a new one."""
    configured = str(os.environ.get(KEY_VAR, "")).strip()
    if configured:
        return _private_from_d(_unb64(configured))
    session = _sys(graph)
    rows = session.find_entities("content", {"type": KEY_RECORD}, limit=1)
    if rows:
        return _private_from_d(_unb64(rows[0]["attrs"]["d"]))
    ec = _ec()
    key = ec.generate_private_key(ec.SECP256R1())
    d = key.private_numbers().private_value.to_bytes(32, "big")
    session.create_entity("content", {"type": KEY_RECORD, "d": _b64(d), "created_at": now_iso()},
                          source=MODULE, owner_id=SYSTEM_OWNER)
    return key


def public_key(graph: Graph) -> str:
    """What the browser subscribes with (`applicationServerKey`)."""
    return _b64(_raw_public(_server_key(graph)))


def _subject(graph: Graph) -> str:
    configured = str(os.environ.get(SUBJECT_VAR, "")).strip()
    if configured:
        return configured
    rows = _sys(graph).find_entities("content", {"type": KEY_RECORD}, limit=1)
    origin = rows[0]["attrs"].get("origin", "") if rows else ""
    return origin or "mailto:lifeos@localhost"


def remember_origin(graph: Graph, origin: str):
    """VAPID's `sub` must be a contact URL; the instance's own https origin is one."""
    origin = str(origin or "").strip()
    if not origin.startswith("https://"):
        return
    _server_key(graph)
    session = _sys(graph)
    rows = session.find_entities("content", {"type": KEY_RECORD}, limit=1)
    if rows and rows[0]["attrs"].get("origin") != origin:
        session.update_entity(rows[0]["id"], {"origin": origin}, source=MODULE)


# ---- VAPID (RFC 8292) -----------------------------------------------------------

def vapid_header(graph: Graph, endpoint: str, now: int | None = None) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    parts = urllib.parse.urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}",
              "exp": int(now if now is not None else time.time()) + TTL_SECONDS,
              "sub": _subject(graph)}
    signing_input = (_b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
                     + "." + _b64(json.dumps(claims, separators=(",", ":")).encode()))
    key = _server_key(graph)
    der = key.sign(signing_input.encode(), _ec().ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    token = signing_input + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={token}, k={_b64(_raw_public(key))}"


# ---- message encryption (RFC 8291 / RFC 8188 aes128gcm) --------------------------

def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(plaintext: bytes, ua_public: bytes, auth_secret: bytes, *,
            server_private=None, salt: bytes | None = None) -> bytes:
    """One aes128gcm record addressed to a browser's key. Returns the request body."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(plaintext) > RECORD_SIZE - 17 - 86:
        raise PushError("message too long for one push record")
    ec = _ec()
    as_key = server_private or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(as_key)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = as_key.exchange(ec.ECDH(), ua_key)

    prk_key = hmac.new(auth_secret, shared, hashlib.sha256).digest()
    ikm = _hkdf_expand(prk_key, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    cek = _hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)

    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


def decrypt(body: bytes, ua_private, auth_secret: bytes) -> bytes:
    """The browser's side, for tests: proves `encrypt` produced something decryptable."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    ec = _ec()
    salt, (rs, idlen) = body[:16], struct.unpack("!IB", body[16:21])
    as_public = body[21:21 + idlen]
    ua_public = _raw_public(ua_private)
    shared = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), as_public))
    prk_key = hmac.new(auth_secret, shared, hashlib.sha256).digest()
    ikm = _hkdf_expand(prk_key, b"WebPush: info\x00" + ua_public + as_public, 32)
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    cek = _hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    padded = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    return padded.rstrip(b"\x00")[:-1]


# ---- subscriptions ---------------------------------------------------------------

def _check_endpoint(endpoint: str) -> str:
    from substrate import safefetch

    endpoint = str(endpoint or "").strip()
    parts = urllib.parse.urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not any(host == h or host.endswith("." + h) for h in PUSH_HOSTS):
        raise PushError("that is not a browser push service this app sends to")
    safefetch.check_url(endpoint)
    return endpoint


def subscribe(graph: Graph, subscription: dict, *, timezone: str = "",
              checkin: bool = True, source: str = MODULE) -> dict:
    """Store this browser's subscription for the caller. Same endpoint twice is one row."""
    sub = subscription or {}
    endpoint = _check_endpoint(sub.get("endpoint", ""))
    keys = sub.get("keys") or {}
    try:
        p256dh, auth = _unb64(keys.get("p256dh", "")), _unb64(keys.get("auth", ""))
    except Exception:
        raise PushError("subscription keys are not base64url")
    if len(p256dh) != 65 or p256dh[0] != 4 or len(auth) != 16:
        raise PushError("subscription keys are not a P-256 key and a 16-byte secret")
    tz = _valid_tz(timezone)
    session = graph.session(MODULE, SCOPES)
    attrs = {"type": SUB_RECORD, "endpoint": endpoint, "p256dh": keys["p256dh"],
             "auth": keys["auth"], "timezone": tz, "checkin": bool(checkin)}
    existing = session.find_entities("content", {"type": SUB_RECORD, "endpoint": endpoint}, limit=1)
    if existing:
        session.update_entity(existing[0]["id"], attrs, source=source)
        return {"subscription_id": existing[0]["id"], "created": False, "timezone": tz}
    if len(session.find_entities("content", {"type": SUB_RECORD}, limit=50)) >= MAX_SUBS_PER_OWNER:
        raise PushError("too many devices subscribed; remove one first")
    sid = session.create_entity("content", {**attrs, "created_at": now_iso()}, source=source)
    return {"subscription_id": sid, "created": True, "timezone": tz}


def _valid_tz(name: str) -> str:
    import zoneinfo
    try:
        zoneinfo.ZoneInfo(str(name or "UTC"))
        return str(name or "UTC")
    except Exception:
        return "UTC"


def subscriptions(graph: Graph) -> list[dict]:
    rows = graph.session(MODULE, SCOPES).find_entities("content", {"type": SUB_RECORD}, limit=50)
    return [{"id": r["id"], "service": urllib.parse.urlsplit(r["attrs"]["endpoint"]).hostname,
             "timezone": r["attrs"].get("timezone", "UTC"), "checkin": r["attrs"].get("checkin", True),
             "last_result": r["attrs"].get("last_result", "")} for r in rows]


def unsubscribe(graph: Graph, subscription_id: str = "", endpoint: str = "") -> dict:
    session = graph.session(MODULE, SCOPES)
    gone = 0
    for r in session.find_entities("content", {"type": SUB_RECORD}, limit=50):
        if r["id"] == subscription_id or (endpoint and r["attrs"].get("endpoint") == endpoint):
            session.delete_entity(r["id"], source=MODULE)
            gone += 1
    return {"removed": gone}


# ---- sending ---------------------------------------------------------------------

def _post(url: str, body: bytes, headers: dict, timeout: int = 15) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def send(graph: Graph, row: dict, message: dict, *, post=None, source: str = MODULE) -> dict:
    """Encrypt and hand one message to one subscription's push service."""
    attrs = row["attrs"]
    payload = json.dumps(message, separators=(",", ":")).encode()[:MAX_PAYLOAD]
    try:
        endpoint = _check_endpoint(attrs["endpoint"])
        body = encrypt(payload, _unb64(attrs["p256dh"]), _unb64(attrs["auth"]))
        status = (post or _post)(endpoint, body, {
            "TTL": str(TTL_SECONDS), "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream", "Urgency": "normal",
            "Authorization": vapid_header(graph, endpoint)})
    except Exception as exc:
        status, error = 0, f"{type(exc).__name__}: {exc}"
    else:
        error = ""
    owner = Graph(graph.conn, graph.bus, default_owner=row.get("owner_id") or graph.default_owner)
    session = owner.session(MODULE, SCOPES)
    if status in (404, 410):
        session.delete_entity(row["id"], source=source)
        return {"push_delivered": False, "status": status,
                "why": "the browser dropped this subscription, so it was removed"}
    delivered = status in (200, 201, 202)
    session.update_entity(row["id"], {"last_result": f"{status or error} at {now_iso()}"}, source=source)
    out = {"push_delivered": delivered, "status": status}
    if not delivered:
        out["why"] = error or f"the push service answered {status}"
    return out


def send_to_owner(graph: Graph, message: dict, *, post=None) -> dict:
    rows = graph.session(MODULE, SCOPES).find_entities("content", {"type": SUB_RECORD}, limit=50)
    results = [send(graph, r, message, post=post) for r in rows]
    return {"devices": len(rows), "delivered": sum(1 for r in results if r["push_delivered"]),
            "push_delivered": any(r["push_delivered"] for r in results), "results": results,
            **({} if rows else {"why": "no device has turned on notifications yet"})}
