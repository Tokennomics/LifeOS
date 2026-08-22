"""The money endpoints over HTTP.

Eleven handlers made statements about money and touched no processor. These pin the
replacements: a refusal that names what is missing, a webhook that actually verifies, and a
one-tap settle that settles the tab rather than dividing a constant.
"""

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app

PW = "correct-horse-battery"
SECRET = "whsec_test_not_a_real_key"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture(autouse=True)
def _no_processor(monkeypatch):
    for var in ("LIFEOS_STRIPE_SECRET_KEY", "LIFEOS_STRIPE_WEBHOOK_SECRET",
                "LIFEOS_PAYPAL_CLIENT_ID", "LIFEOS_PAYPAL_SECRET"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def world(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


# ---- charging refuses, and says what is missing --------------------------------

@pytest.mark.parametrize("path,needs", [
    ("/v1/payments/stripe/checkout-session", "LIFEOS_STRIPE_SECRET_KEY"),
    ("/v1/payments/paypal/create-order", "LIFEOS_PAYPAL_CLIENT_ID"),
    ("/v1/payments/paypal/capture-order", "LIFEOS_PAYPAL_CLIENT_ID"),
    ("/v1/billing/subscriptions", "LIFEOS_STRIPE_SECRET_KEY"),
    ("/v1/monetization/b2b-team-tier", "LIFEOS_STRIPE_SECRET_KEY"),
])
def test_charging_refuses_with_503_and_names_the_missing_keys(world, path, needs):
    client, people = world
    res = client.post(path, json={"amount": 21.00}, headers=people["ana"]["h"])
    assert res.status_code == 503, f"{path} answered {res.status_code}"
    detail = res.json()["detail"]
    assert detail["charged"] is False
    assert detail["money_moved"] is False
    assert needs in detail["needs"]


def test_a_refusal_mints_no_identifier(world):
    """Every id the old handlers returned was a constant shared by every caller."""
    client, people = world
    res = client.post("/v1/payments/stripe/checkout-session", json={},
                      headers=people["ana"]["h"])
    body = res.text
    for invented in ("cs_live_", "pi_3MtwBw", "PAYPAL-ORDER-882194A", "CAP-882194A",
                     "checkout.stripe.com", "paypal.com/checkoutnow"):
        assert invented not in body


def test_a_subscription_is_never_reported_as_active(world):
    """It answered `subscribed: True` at €9.99/mo, charging nobody and gating nothing."""
    client, people = world
    res = client.post("/v1/billing/subscriptions", json={"plan": "EXPLORER_PRO"},
                      headers=people["ana"]["h"])
    assert res.status_code == 503
    assert "subscribed" not in res.text
    assert "9.99" not in res.text


# ---- the webhook ---------------------------------------------------------------

def _sign(payload: bytes, stamp: int, secret: str = SECRET) -> str:
    mac = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256)
    return f"t={stamp},v1={mac.hexdigest()}"


def test_the_webhook_refuses_any_body_when_no_secret_is_set(world):
    """The old handler answered `signature_verified: True` and `PAID_AND_SETTLED` to an
    empty object, with nothing configured and nothing checked."""
    client, people = world
    res = client.post("/v1/payments/stripe/webhook", json={}, headers=people["ana"]["h"])
    assert res.status_code == 503
    assert res.json()["detail"]["verified"] is False
    assert "PAID_AND_SETTLED" not in res.text
    assert "signature_verified" not in res.text


def test_an_unsigned_body_is_rejected_when_a_secret_is_set(world, monkeypatch):
    monkeypatch.setenv("LIFEOS_STRIPE_WEBHOOK_SECRET", SECRET)
    client, people = world
    res = client.post("/v1/payments/stripe/webhook", json={"type": "payout.paid"},
                      headers=people["ana"]["h"])
    assert res.status_code == 400


def test_a_genuinely_signed_body_is_accepted(world, monkeypatch):
    monkeypatch.setenv("LIFEOS_STRIPE_WEBHOOK_SECRET", SECRET)
    client, people = world
    payload = b'{"id":"evt_1","type":"checkout.session.completed"}'
    headers = {**people["ana"]["h"],
               "stripe-signature": _sign(payload, int(time.time())),
               "content-type": "application/json"}
    res = client.post("/v1/payments/stripe/webhook", content=payload, headers=headers)
    assert res.status_code == 200
    out = res.json()
    assert out["verified"] is True
    # Verified is not settled: the signature is genuine, the money still did not move.
    assert out["settled"] is False


def test_a_body_altered_after_signing_is_rejected(world, monkeypatch):
    """The property the raw-body read exists for: re-serialising parsed JSON would change
    the bytes and break verification, or worse, silently verify the wrong thing."""
    monkeypatch.setenv("LIFEOS_STRIPE_WEBHOOK_SECRET", SECRET)
    client, people = world
    signed = b'{"id":"evt_1","type":"checkout.session.completed"}'
    tampered = b'{"id":"evt_1","type":"payout.paid"}'
    headers = {**people["ana"]["h"],
               "stripe-signature": _sign(signed, int(time.time())),
               "content-type": "application/json"}
    res = client.post("/v1/payments/stripe/webhook", content=tampered, headers=headers)
    assert res.status_code == 400


# ---- one-tap settle now settles -------------------------------------------------

def test_one_tap_settle_clears_what_the_tab_actually_holds(world):
    client, people = world
    put = client.post("/v1/ledger/quick-split",
                      json={"participants": [people["bruno"]["id"]], "amount": "40.00",
                            "currency": "EUR", "note": "dinner"},
                      headers=people["ana"]["h"])
    assert put.status_code == 200, put.text

    owing = client.get("/v1/ledger/tab", headers=people["bruno"]["h"]).json()
    assert owing["you_owe"]["EUR"] == 20.00

    out = client.post("/v1/payments/one-tap-settle", json={},
                      headers=people["bruno"]["h"]).json()
    assert out["count"] == 1
    assert out["cleared"]["EUR"] == 20.00
    assert out["money_moved"] is False

    after = client.get("/v1/ledger/tab", headers=people["bruno"]["h"]).json()
    assert after["empty"] is True


def test_one_tap_settle_does_not_clear_what_you_are_owed(world):
    """Clearing both directions from one phone would erase money coming your way."""
    client, people = world
    put = client.post("/v1/ledger/quick-split",
                      json={"participants": [people["bruno"]["id"]], "amount": "40.00",
                            "currency": "EUR", "note": "dinner"},
                      headers=people["ana"]["h"])
    assert put.status_code == 200, put.text

    out = client.post("/v1/payments/one-tap-settle", json={},
                      headers=people["ana"]["h"]).json()
    assert out["nothing_owed"] is True
    assert out["count"] == 0

    # Bruno still owes her.
    still = client.get("/v1/ledger/tab", headers=people["ana"]["h"]).json()
    assert still["owed_to_you"]["EUR"] == 20.00


def test_one_tap_settle_uses_the_real_amount_not_a_constant(world):
    """It divided a hardcoded 84.00 by the headcount, so a bill of 200 between four
    reported 21.00 each whatever was passed in."""
    client, people = world
    put = client.post("/v1/ledger/quick-split",
                      json={"participants": [people["bruno"]["id"]], "amount": "200.00",
                            "currency": "EUR"},
                      headers=people["ana"]["h"])
    assert put.status_code == 200, put.text
    out = client.post("/v1/payments/one-tap-settle",
                      json={"bill_total": "€200.00", "members_count": 4},
                      headers=people["bruno"]["h"]).json()
    assert out["cleared"]["EUR"] == 100.00
    assert "21.00" not in str(out)
    assert "revolut.me" not in str(out)


# ---- revenue is counted, not quoted ---------------------------------------------

@pytest.mark.parametrize("path", [
    "/v1/economics/revenue-share",
    "/v1/monetization/venue-commissions",
    "/v1/monetization/plugin-revshare",
])
def test_revenue_reads_zero_and_explains_itself(world, path):
    client, people = world
    out = client.get(path, headers=people["ana"]["h"]).json()
    assert out["earnings"] == 0
    assert out["payout_ready"] is False
    assert out["reason"]


@pytest.mark.parametrize("path,invented", [
    ("/v1/economics/revenue-share", ("145", "READY_FOR_PAYOUT", "Rooftop Sunset Meet")),
    ("/v1/monetization/venue-commissions", ("380", "160", "4.5%")),
    ("/v1/monetization/plugin-revshare", ("850", "150", "85%")),
])
def test_no_revenue_figure_survives(world, path, invented):
    client, people = world
    body = client.get(path, headers=people["ana"]["h"]).text
    for figure in invented:
        assert figure not in body, f"{path} still reports {figure}"


def test_sponsored_perks_lists_nothing_because_nobody_agreed_one(world):
    """A member who presented `PERK-FABRICA-FREE` at the counter would have been turned
    away, having been told by this app that it was theirs."""
    client, people = world
    out = client.get("/v1/monetization/sponsored-perks", headers=people["ana"]["h"]).json()
    assert out["perks"] == []
    assert out["sponsored"] is False
    assert "PERK-" not in str(out)
    assert "Fabrica" not in str(out)


def test_none_of_these_endpoints_answer_an_unsigned_caller(world):
    client, _ = world
    for path in ("/v1/payments/stripe/checkout-session", "/v1/payments/one-tap-settle",
                 "/v1/billing/subscriptions", "/v1/monetization/b2b-team-tier"):
        assert client.post(path, json={}).status_code == 401, path
    for path in ("/v1/economics/revenue-share", "/v1/monetization/venue-commissions",
                 "/v1/monetization/plugin-revshare", "/v1/monetization/sponsored-perks"):
        assert client.get(path).status_code == 401, path


def test_a_cleared_row_names_the_person_not_their_id(world):
    """Only visible from the app: the panel rendered `af95493f-3cf5-… · 30 EUR`.

    `_with_handles` resolved names on `balances` and `entries` but not on `settled`, so the
    one screen that reports a settlement showed a UUID. A balance nobody can read is a
    balance nobody can act on.
    """
    client, people = world
    put = client.post("/v1/ledger/quick-split",
                      json={"participants": [people["bruno"]["id"]], "amount": "60.00",
                            "currency": "EUR"},
                      headers=people["ana"]["h"])
    assert put.status_code == 200, put.text

    out = client.post("/v1/payments/one-tap-settle", json={},
                      headers=people["bruno"]["h"]).json()
    assert [row["handle"] for row in out["settled"]] == ["ana"]


def test_settling_one_currency_does_not_report_you_as_clear(world):
    """`clear` has to mean "you owe nothing", not "the call worked". With a currency
    filter, everything in the other currencies is still standing."""
    client, people = world
    for amount, currency in (("40.00", "EUR"), ("30.00", "GBP")):
        put = client.post("/v1/ledger/quick-split",
                          json={"participants": [people["bruno"]["id"]],
                                "amount": amount, "currency": currency},
                          headers=people["ana"]["h"])
        assert put.status_code == 200, put.text

    out = client.post("/v1/payments/one-tap-settle", json={"currency": "EUR"},
                      headers=people["bruno"]["h"]).json()
    assert out["cleared"] == {"EUR": 20.00}
    assert out["clear"] is False, "he still owes 15.00 in GBP"

    rest = client.post("/v1/payments/one-tap-settle", json={},
                       headers=people["bruno"]["h"]).json()
    assert rest["clear"] is True
