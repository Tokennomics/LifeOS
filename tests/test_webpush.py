"""Web Push: real encryption, a real signature, and "delivered" only when it was.

The encryption is checked by decrypting as a browser would. During development it was also
cross-checked against the independent `http_ece` implementation, which decrypted the output
correctly. The VAPID token is checked by verifying its signature with the public key the
browser subscribes with. Sending is checked against a fake push service, so the tests need
no network. They prove what is POSTed, not that Google answers.
"""

import base64
import datetime
import json
import os

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.agent import core
from modules.notifications import checkins, webpush

ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv(webpush.KEY_VAR, raising=False)
    monkeypatch.delenv(webpush.SUBJECT_VAR, raising=False)
    monkeypatch.delenv(checkins.ENABLE_VAR, raising=False)
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _browser():
    """A browser's push subscription: its own P-256 key and a 16-byte auth secret."""
    key = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
           "keys": {"p256dh": _b64(webpush._raw_public(key)), "auth": _b64(auth)}}
    return key, auth, sub


class FakePushService:
    def __init__(self, status=201):
        self.status, self.calls = status, []

    def __call__(self, url, body, headers):
        self.calls.append({"url": url, "body": body, "headers": headers})
        return self.status


# ---- crypto -------------------------------------------------------------------------

def test_the_browser_can_decrypt_what_is_sent():
    key, auth, sub = _browser()
    msg = b'{"title":"t","body":"Fado night at 21:00"}'
    body = webpush.encrypt(msg, webpush._unb64(sub["keys"]["p256dh"]), auth)
    assert webpush.decrypt(body, key, auth) == msg
    assert body[16:20] == (4096).to_bytes(4, "big") and body[20] == 65


def test_a_different_browser_cannot():
    _, auth, sub = _browser()
    other, _, _ = _browser()
    body = webpush.encrypt(b"secret", webpush._unb64(sub["keys"]["p256dh"]), auth)
    with pytest.raises(Exception):
        webpush.decrypt(body, other, auth)


def test_the_vapid_token_verifies_with_the_public_key(graph):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    header = webpush.vapid_header(graph, "https://fcm.googleapis.com/fcm/send/x", now=1000)
    token = header.split("t=")[1].split(",")[0]
    k = header.split("k=")[1]
    assert k == webpush.public_key(graph)
    head, claims, sig = token.split(".")
    payload = json.loads(webpush._unb64(claims))
    assert payload["aud"] == "https://fcm.googleapis.com" and payload["exp"] == 1000 + 12 * 3600
    raw = webpush._unb64(sig)
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush._unb64(k))
    public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                  f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_the_key_is_made_once_and_kept(graph):
    first = webpush.public_key(graph)
    assert webpush.public_key(graph) == first and len(webpush._unb64(first)) == 65


# ---- subscriptions ----------------------------------------------------------------------

@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/x",            # not https
    "https://evil.example/push",                        # not a push service
    "https://fcm.googleapis.com.evil.example/x",        # lookalike host
    "https://127.0.0.1/push",
])
def test_only_real_push_services_over_https_are_accepted(graph, endpoint):
    _, _, sub = _browser()
    sub["endpoint"] = endpoint
    with pytest.raises(webpush.PushError):
        webpush.subscribe(graph, sub)


def test_bad_keys_are_refused(graph):
    _, _, sub = _browser()
    sub["keys"]["auth"] = _b64(b"short")
    with pytest.raises(webpush.PushError):
        webpush.subscribe(graph, sub)


def test_the_same_device_twice_is_one_row_and_an_odd_timezone_is_utc(graph):
    _, _, sub = _browser()
    assert webpush.subscribe(graph, sub, timezone="Europe/Lisbon")["created"] is True
    again = webpush.subscribe(graph, sub, timezone="Not/AZone")
    assert again["created"] is False and again["timezone"] == "UTC"
    assert len(webpush.subscriptions(graph)) == 1


# ---- sending ---------------------------------------------------------------------------

def test_delivered_means_the_push_service_accepted_it(graph):
    key, auth, sub = _browser()
    webpush.subscribe(graph, sub)
    service = FakePushService(201)
    out = webpush.send_to_owner(graph, {"title": "hi"}, post=service)
    assert out["push_delivered"] is True and out["delivered"] == 1
    call = service.calls[0]
    assert call["headers"]["Content-Encoding"] == "aes128gcm"
    assert call["headers"]["Authorization"].startswith("vapid t=")
    assert json.loads(webpush.decrypt(call["body"], key, auth)) == {"title": "hi"}


def test_a_refusal_is_not_delivery(graph):
    _, _, sub = _browser()
    webpush.subscribe(graph, sub)
    out = webpush.send_to_owner(graph, {"title": "hi"}, post=FakePushService(500))
    assert out["push_delivered"] is False and "500" in out["results"][0]["why"]


def test_a_gone_subscription_is_removed(graph):
    _, _, sub = _browser()
    webpush.subscribe(graph, sub)
    out = webpush.send_to_owner(graph, {"title": "hi"}, post=FakePushService(410))
    assert out["push_delivered"] is False and webpush.subscriptions(graph) == []


def test_no_devices_says_so(graph):
    out = webpush.send_to_owner(graph, {"title": "hi"}, post=FakePushService())
    assert out == {"devices": 0, "delivered": 0, "push_delivered": False, "results": [],
                   "why": "no device has turned on notifications yet"}


# ---- the morning check-in -------------------------------------------------------------------

def _at(hour, tz="Europe/Lisbon"):
    import zoneinfo
    return datetime.datetime(2026, 10, 5, hour, 30, tzinfo=zoneinfo.ZoneInfo(tz))


def test_a_check_in_goes_out_in_the_local_morning_once(graph):
    key, auth, sub = _browser()
    webpush.subscribe(graph, sub, timezone="Europe/Lisbon")
    core.propose(graph, "remember", {"text": "x"})
    service = FakePushService()
    assert checkins.run_once(graph, now=_at(6), post=service)["not_due"] == 1
    out = checkins.run_once(graph, now=_at(8), post=service)
    assert out["delivered"] == 1
    sent = json.loads(webpush.decrypt(service.calls[0]["body"], key, auth))
    assert sent["title"] == "Your morning check-in" and "waiting for your approval" in sent["body"]
    assert checkins.run_once(graph, now=_at(11), post=service)["delivered"] == 0
    assert len(service.calls) == 1


def test_a_quiet_day_sends_nothing(graph):
    _, _, sub = _browser()
    webpush.subscribe(graph, sub, timezone="Europe/Lisbon")
    service = FakePushService()
    out = checkins.run_once(graph, now=_at(9), post=service)
    assert out["quiet"] == 1 and service.calls == []


def test_a_device_that_opted_out_gets_nothing(graph):
    _, _, sub = _browser()
    webpush.subscribe(graph, sub, timezone="Europe/Lisbon", checkin=False)
    core.propose(graph, "remember", {"text": "x"})
    service = FakePushService()
    checkins.run_once(graph, now=_at(9), post=service)
    assert service.calls == []


def test_the_loop_is_off_unless_configured(graph, monkeypatch):
    monkeypatch.setattr(checkins, "_STARTED", False)
    assert checkins.start(graph) is False


# ---- routes ------------------------------------------------------------------------------

def test_the_routes(cfg, monkeypatch):
    client = TestClient(create_app(cfg))
    key = client.get("/v1/push/key").json()
    assert len(webpush._unb64(key["public_key"])) == 65
    _, _, sub = _browser()
    r = client.post("/v1/push/subscribe", json={"subscription": sub, "timezone": "Europe/Lisbon"})
    assert r.status_code == 200 and r.json()["created"] is True
    bad = dict(sub, endpoint="https://evil.example/x")
    assert client.post("/v1/push/subscribe", json={"subscription": bad}).status_code == 400
    monkeypatch.setattr(webpush, "_post", FakePushService(201))
    test = client.post("/v1/push/test").json()
    assert test["push_delivered"] is True
    assert client.get("/v1/push/subscriptions").json()["subscriptions"][0]["timezone"] == "Europe/Lisbon"
    sid = client.get("/v1/push/subscriptions").json()["subscriptions"][0]["id"]
    assert client.request("DELETE", "/v1/push/subscribe", json={"subscription_id": sid}).json()["removed"] == 1
