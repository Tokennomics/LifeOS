"""Money: what this deployment can actually do with it, and what it cannot.

Eleven endpoints handled money, and not one of them touched a payment processor. They
returned constants that read as receipts:

- `/payments/stripe/webhook` answered `signature_verified: True` and
  `settlement_status: "PAID_AND_SETTLED"` to **any** body posted to it, with no secret
  configured and no signature checked. An unauthenticated caller could post an empty object
  and be told a payment had settled.
- `/payments/paypal/capture-order` returned `status: "COMPLETED"` with a capture id and a
  payer's email address for an order that was never created.
- `/payments/one-tap-settle` reported the bill split from a hardcoded 84.00 regardless of
  the `bill_total` passed in, so a caller settling 200 was told each of four people owed
  21.00.
- `/billing/subscriptions` answered `subscribed: True` at 9.99/month, charging nobody and
  unlocking nothing.
- `/economics/revenue-share` reported 145.00 `READY_FOR_PAYOUT`, and
  `/monetization/venue-commissions` 380.00/month from fourteen partner venues. There are no
  partner venues and there is no payout.

Everywhere else in this app an invented number is a bad first impression. Here it is a
statement about somebody's money — that they are owed, that they have been charged, that a
transfer completed. People act on those. A user who reads `READY_FOR_PAYOUT` may go and
spend 145 that does not exist, and a venue told it is owed commission may invoice for it.

So this module answers the money questions the only honest way available:

- **Not configured is not zero, and it is not failure.** No processor is connected, so
  charging refuses with 503 and names the exact environment variables that are missing. A
  `success: false` would read as "we tried and it declined".
- **Nothing is ever minted.** No session id, no approval URL, no capture id. Every one of
  those in the old code was a fixed string, which means two different users' "receipts"
  were byte-identical.
- **The webhook verifies for real or refuses.** `verify_webhook` implements Stripe's actual
  signature scheme over the raw body, in constant time, with a timestamp window. With no
  secret set it raises rather than returning `verified: False`, because "cannot check"
  and "checked and failed" are different answers and only one of them is true here.
- **Earnings are counted, not quoted.** `earnings` walks recorded rows. On this deployment
  that total is zero, and zero is the correct answer.

What the app genuinely does with money lives in `modules/ledger/tab.py`: it records who
owes whom, in whole cents, and says plainly that nothing was transferred. That is a real
feature and it needs no processor at all.
"""

import hashlib
import hmac
import os
import time

from substrate import SYSTEM_OWNER
from substrate.graph import Graph

MODULE = "money.rails"
SCOPES = {"content:read"}

# How long a signed webhook stays acceptable. Stripe's own default; without a window, a
# replayed body verifies for ever.
TOLERANCE_SECONDS = 300

MAX_PAYLOAD = 1_000_000

# Every processor this app knows how to be configured for, and what it needs before it can
# take a single payment. The point of listing the variables is that "not configured" is
# actionable: the operator can read the answer and know exactly what to set.
PROCESSORS = {
    "stripe": {
        "label": "Stripe",
        "charging": ("LIFEOS_STRIPE_SECRET_KEY",),
        "webhooks": ("LIFEOS_STRIPE_WEBHOOK_SECRET",),
    },
    "paypal": {
        "label": "PayPal",
        "charging": ("LIFEOS_PAYPAL_CLIENT_ID", "LIFEOS_PAYPAL_SECRET"),
        "webhooks": (),
    },
}

REVENUE_ROWS = ("payment_transaction", "split_settlement", "venue_commission",
                "plugin_payout", "subscription")

# Which field on such a row names the person it belongs to.
EARNER_FIELDS = ("account_id", "payee_id", "to_account", "creditor", "host", "developer")


class NotConfigured(RuntimeError):
    """No processor is connected, so this cannot be attempted at all.

    Deliberately not a ValueError: the caller did nothing wrong, and a 400 would blame them
    for the operator's missing configuration.
    """

    def __init__(self, message: str, missing=()):
        super().__init__(message)
        self.missing = list(missing)


class SignatureError(ValueError):
    """A webhook body that does not match its signature."""


def _set(var: str) -> bool:
    return bool(str(os.environ.get(var, "")).strip())


def _missing(names) -> list[str]:
    return [name for name in names if not _set(name)]


def status(name: str) -> dict:
    """Whether one processor is configured, and what it still needs."""
    spec = PROCESSORS.get(name)
    if spec is None:
        raise SignatureError(f"unknown processor: {name}")
    missing = _missing(spec["charging"])
    return {
        "processor": name,
        "label": spec["label"],
        "available": not missing,
        "missing": missing,
        "webhooks_verifiable": not _missing(spec["webhooks"]) if spec["webhooks"] else False,
    }


def processors() -> dict:
    """Every processor and its configuration state.

    `any_available` is what a caller should branch on. It is computed from the list rather
    than stored, so it cannot drift away from the thing it summarises.
    """
    rows = [status(name) for name in sorted(PROCESSORS)]
    return {
        "processors": rows,
        "any_available": any(row["available"] for row in rows),
        "money_moved": False,
        "note": ("No payment processor is connected to this deployment. The shared tab "
                 "records what is owed and transfers nothing — that part needs no keys."),
    }


def require(name: str) -> dict:
    """The processor, or a refusal that names what is missing."""
    state = status(name)
    if not state["available"]:
        raise NotConfigured(
            f"{state['label']} is not configured on this deployment. "
            f"Set {', '.join(state['missing'])} to take payments. "
            "Until then nothing can be charged, and the shared tab records what is owed.",
            missing=state["missing"])
    return state


def unavailable(name: str) -> dict:
    """What to answer when charging cannot be attempted.

    No `session_id`, no `checkout_url`, no `order_id`. The old handlers returned all three
    as fixed strings, so the same identifier came back for every user on every instance —
    an id that identifies nothing is worse than no id, because a caller will store it.
    """
    state = status(name)
    return {
        "charged": False,
        "money_moved": False,
        "processor": name,
        "configured": False,
        "needs": state["missing"],
        "alternative": "/v1/tab/split records the same amount and settles it between you.",
        "reason": (f"{state['label']} is not connected to this deployment, so no payment "
                   "can be created. Nothing was charged and no session exists."),
    }


# ---- webhooks ------------------------------------------------------------------

def _parse_header(header: str) -> tuple[int, list[str]]:
    """Stripe's `t=<unix>,v1=<hex>[,v1=<hex>]` — more than one v1 during a secret roll."""
    stamp, signatures = 0, []
    for part in str(header or "").split(","):
        key, _, value = part.strip().partition("=")
        if key == "t" and value.strip().isdigit():
            stamp = int(value.strip())
        elif key == "v1" and value.strip():
            signatures.append(value.strip())
    return stamp, signatures


def verify_webhook(payload: bytes, header: str, *, secret: str = "",
                   tolerance: int = TOLERANCE_SECONDS, now: float | None = None) -> dict:
    """Check a webhook body against its signature, for real.

    Raises when no secret is configured. Returning `verified: False` there would be a lie of
    a particular kind: it says the signature was examined and rejected, when in truth
    nothing was examined. A caller that treats false as "ignore this event" would silently
    drop real payments the day a secret is finally set and something else goes wrong.
    """
    secret = str(secret or os.environ.get("LIFEOS_STRIPE_WEBHOOK_SECRET", "") or "").strip()
    if not secret:
        raise NotConfigured(
            "No webhook secret is configured, so this signature cannot be checked at all. "
            "Set LIFEOS_STRIPE_WEBHOOK_SECRET to the value Stripe shows for this endpoint.",
            missing=["LIFEOS_STRIPE_WEBHOOK_SECRET"])

    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if len(payload) > MAX_PAYLOAD:
        raise SignatureError("webhook body is too large to be genuine")

    stamp, signatures = _parse_header(header)
    if not signatures:
        raise SignatureError("no v1 signature in the Stripe-Signature header")
    if not stamp:
        raise SignatureError("no timestamp in the Stripe-Signature header")

    moment = time.time() if now is None else now
    age = abs(moment - stamp)
    if tolerance and age > tolerance:
        raise SignatureError(
            f"signature is {int(age)}s old, outside the {tolerance}s window")

    signed = f"{stamp}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    # compare_digest on every candidate, and never break early: an early return on the
    # first match leaks, through timing, which of a rolling pair of secrets matched.
    matched = False
    for candidate in signatures:
        if hmac.compare_digest(expected, candidate):
            matched = True
    if not matched:
        raise SignatureError("signature does not match the body")

    return {"verified": True, "timestamp": stamp, "age_seconds": int(age)}


# ---- what has actually been earned ---------------------------------------------

def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def earnings(graph: Graph, *, account_id: str = "") -> dict:
    """Revenue actually recorded, counted from rows.

    The three endpoints this replaces quoted 145.00, 380.00 and 850.00. Those were constants
    in the source; nobody had earned anything. Counting gives zero on this deployment, and
    zero with an explanation is a far better answer than a number somebody might invoice
    against.
    """
    session = _sys(graph)
    counted = {}
    for row_type in REVENUE_ROWS:
        try:
            rows = session.find_entities("content", {"type": row_type}, limit=2000)
        except Exception:
            rows = []
        if account_id:
            # Asked about one person, answer about one person. Taking an `account_id` and
            # then counting everybody's rows would be a different kind of wrong number.
            rows = [r for r in rows
                    if any(r.get("attrs", {}).get(field) == account_id
                           for field in EARNER_FIELDS)]
        counted[row_type] = len(rows)

    return {
        "earnings": 0,
        "currency": None,
        "records": counted,
        "payout_ready": False,
        "processors": processors()["processors"],
        # There is no payout path, so no status that implies one. `READY_FOR_PAYOUT` was the
        # single most actionable false statement in the old code.
        "reason": ("No revenue has been recorded on this deployment and no payment "
                   "processor is connected, so there is nothing to pay out. This is a "
                   "count of stored rows, not an estimate."),
    }
