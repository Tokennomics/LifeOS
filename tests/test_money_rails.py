"""The money module: verification that verifies, and counts that count.

The endpoints these back were the only ones in the repo whose invented output was a
statement about somebody's money. The tests are written against the two properties that
matter: a signature is either genuinely checked or the call refuses, and a number is either
counted from rows or it is not reported.
"""

import hashlib
import hmac
import time

import pytest

from modules.money import rails

# Not spelled in Stripe's namespace on purpose: `test_no_vendor_credential_prefixes_are_committed`
# flags anything shaped like a real credential, because demo data that looks like a leak
# reads as one to every scanner including GitHub's. It is only ever an HMAC key here.
SECRET = "a-signing-key-for-this-suite-only"
BODY = b'{"id":"evt_1","type":"checkout.session.completed"}'


def _sign(payload: bytes, stamp: int, secret: str = SECRET) -> str:
    mac = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256)
    return f"t={stamp},v1={mac.hexdigest()}"


# ---- configuration ------------------------------------------------------------

def test_nothing_is_configured_by_default():
    state = rails.processors()
    assert state["any_available"] is False
    assert state["money_moved"] is False
    for row in state["processors"]:
        assert row["available"] is False
        assert row["missing"], "an unavailable processor must name what it needs"


def test_a_processor_becomes_available_when_its_keys_are_set(monkeypatch):
    monkeypatch.setenv("LIFEOS_STRIPE_SECRET_KEY", "a-placeholder-api-key")
    assert rails.status("stripe")["available"] is True
    assert rails.status("stripe")["missing"] == []
    # PayPal needs two, and one is not enough.
    monkeypatch.setenv("LIFEOS_PAYPAL_CLIENT_ID", "id")
    paypal = rails.status("paypal")
    assert paypal["available"] is False
    assert paypal["missing"] == ["LIFEOS_PAYPAL_SECRET"]


def test_refusing_names_the_variables_to_set():
    with pytest.raises(rails.NotConfigured) as caught:
        rails.require("stripe")
    assert caught.value.missing == ["LIFEOS_STRIPE_SECRET_KEY"]
    assert "LIFEOS_STRIPE_SECRET_KEY" in str(caught.value)


def test_nothing_mints_an_identifier():
    """Every id in the old handlers was a constant, so two users got the same receipt."""
    answer = rails.unavailable("stripe")
    assert answer["charged"] is False
    assert answer["money_moved"] is False
    for banned in ("session_id", "checkout_url", "payment_intent", "order_id",
                   "capture_id", "approval_url", "receipt_url"):
        assert banned not in answer


# ---- webhook signatures -------------------------------------------------------

def test_a_genuine_signature_verifies():
    stamp = int(time.time())
    out = rails.verify_webhook(BODY, _sign(BODY, stamp), secret=SECRET)
    assert out["verified"] is True
    assert out["timestamp"] == stamp


def test_a_tampered_body_is_refused():
    stamp = int(time.time())
    header = _sign(BODY, stamp)
    with pytest.raises(rails.SignatureError):
        rails.verify_webhook(b'{"id":"evt_1","type":"payout.paid"}', header, secret=SECRET)


def test_a_signature_from_another_secret_is_refused():
    stamp = int(time.time())
    with pytest.raises(rails.SignatureError):
        rails.verify_webhook(BODY, _sign(BODY, stamp, "a-different-signing-key"), secret=SECRET)


def test_a_replayed_signature_expires():
    old = int(time.time()) - (rails.TOLERANCE_SECONDS + 60)
    with pytest.raises(rails.SignatureError) as caught:
        rails.verify_webhook(BODY, _sign(BODY, old), secret=SECRET)
    assert "window" in str(caught.value)


def test_a_header_without_a_signature_is_refused():
    stamp = int(time.time())
    for header in ("", f"t={stamp}", "v1=deadbeef", "nonsense"):
        with pytest.raises(rails.SignatureError):
            rails.verify_webhook(BODY, header, secret=SECRET)


def test_a_rolling_secret_pair_still_verifies():
    """Stripe sends two v1 signatures while a secret is being rotated."""
    stamp = int(time.time())
    stale = hmac.new(b"the-previous-signing-key", f"{stamp}.".encode() + BODY,
                     hashlib.sha256).hexdigest()
    live = _sign(BODY, stamp).split("v1=")[1]
    out = rails.verify_webhook(BODY, f"t={stamp},v1={stale},v1={live}", secret=SECRET)
    assert out["verified"] is True


def test_no_secret_refuses_rather_than_reporting_unverified(monkeypatch):
    """The distinction the old handler destroyed.

    `verified: False` says the signature was examined and rejected. With no secret nothing
    was examined at all, and a caller that treats false as "drop this event" would silently
    discard real payments.
    """
    monkeypatch.delenv("LIFEOS_STRIPE_WEBHOOK_SECRET", raising=False)
    stamp = int(time.time())
    with pytest.raises(rails.NotConfigured) as caught:
        rails.verify_webhook(BODY, _sign(BODY, stamp), secret="")
    assert caught.value.missing == ["LIFEOS_STRIPE_WEBHOOK_SECRET"]


def test_the_secret_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LIFEOS_STRIPE_WEBHOOK_SECRET", SECRET)
    stamp = int(time.time())
    assert rails.verify_webhook(BODY, _sign(BODY, stamp))["verified"] is True


def test_an_oversized_body_is_refused():
    stamp = int(time.time())
    huge = b"x" * (rails.MAX_PAYLOAD + 1)
    with pytest.raises(rails.SignatureError):
        rails.verify_webhook(huge, _sign(huge, stamp), secret=SECRET)


# ---- earnings -----------------------------------------------------------------

def test_earnings_are_zero_and_say_why(graph):
    out = rails.earnings(graph)
    assert out["earnings"] == 0
    assert out["payout_ready"] is False
    assert out["currency"] is None
    assert out["reason"]


def test_no_earnings_figure_is_a_quoted_constant(graph):
    """145.00, 380.00 and 850.00 were the three numbers in the source."""
    body = str(rails.earnings(graph))
    for invented in ("145", "380", "850", "READY_FOR_PAYOUT"):
        assert invented not in body
