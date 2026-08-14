"""Webhooks that are actually sent, and signed so the receiver can tell.

`POST /developers/webhooks` returned `webhook_registered: True`, a signing secret and
`signature_header: "X-ConnectOS-Signature (HMAC-SHA256)"`. Nothing was registered and
nothing was ever sent, so an integrator would build a receiver, verify a signature that
never arrived, and conclude their own code was broken.

The real version, and the two things that make it safe rather than just present:

- **Every delivery is signed.** `X-LifeOS-Signature: sha256=<hex>` over
  `<timestamp>.<body>`, with the timestamp in its own header. Signing the timestamp with
  the body is what stops a captured delivery being replayed a week later; signing the body
  alone does not.
- **The target URL goes through `safefetch`.** A webhook is a URL a *user* chose that the
  *server* fetches — textbook SSRF. Without the address check, `http://169.254.169.254/...`
  as a webhook target is a complete credential theft on any cloud host, and it would look
  like an ordinary integration.

Delivery is synchronous and best-effort, and says so. There is no background worker in this
app, so `dispatch` is called at the moment something happens and failures are recorded
rather than retried forever. That is a real limitation and it is reported in the response —
an integrator who knows deliveries are at-most-once builds differently from one who assumes
a retry queue that does not exist.
"""

import hashlib
import hmac
import json
import secrets
import time

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "platform.webhooks"
SCOPES = {"content:read", "content:write"}
RECORD = "webhook"
DELIVERY = "webhook_delivery"

# Deliberately not `whsec_`: that is Stripe's prefix, and the repo's secret
# scanner flags it on sight. A credential prefix that collides with a vendor's
# makes every future scan a judgement call, which is how a real leak gets waved
# through.
SECRET_PREFIX = "los_wh_"
SIGNATURE_HEADER = "X-LifeOS-Signature"
TIMESTAMP_HEADER = "X-LifeOS-Timestamp"
MAX_HOOKS = 10
MAX_EVENTS = 20
TIMEOUT_S = 8
MAX_DELIVERIES_KEPT = 100

# The events this app can actually emit. A subscription to an event that will never fire is
# a support ticket six months later, so an unknown one is refused at subscribe time.
KNOWN_EVENTS = (
    "meetup.created", "meetup.joined", "checkin.created",
    "kudos.sent", "review.written", "signal.opened", "walk.started",
)


class WebhookError(ValueError):
    """A subscription that cannot be made."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def events() -> list[str]:
    return list(KNOWN_EVENTS)


def sign(secret: str, body: str, timestamp: str) -> str:
    """`sha256=<hex>` over `<timestamp>.<body>`.

    Public because a receiver has to recompute it, and an integrator should be able to read
    exactly what is signed rather than guess from a header name.
    """
    payload = f"{timestamp}.{body}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def subscribe(graph: Graph, url: str, event_names, *, account_id: str,
              source: str = MODULE) -> dict:
    """Register a target. The signing secret is returned once and stored hashed."""
    from substrate import safefetch

    if not account_id:
        raise WebhookError("sign in first")
    url = str(url or "").strip()
    if not url:
        raise WebhookError("where should deliveries go?")
    try:
        # Checked here as well as at delivery: refusing a bad target at subscribe time is a
        # clear error message, and refusing it at delivery time is a mystery.
        safefetch.check_url(url)
    except Exception as exc:
        # A host that does not resolve *right now* is not the same as a dangerous one. DNS
        # is flaky, staging hostnames appear later, and rejecting a subscription for it
        # would make this gate fail closed on an ordinary integration. The address check
        # that actually matters runs again at delivery, where the answer is current — and an
        # IP literal like 169.254.169.254 is still refused here, because catching that needs
        # no DNS at all.
        if "cannot resolve" not in str(exc):
            raise WebhookError(f"that URL cannot be used as a target: {exc}")

    wanted = [str(e).strip() for e in (event_names or []) if str(e).strip()][:MAX_EVENTS]
    if not wanted:
        raise WebhookError(f"subscribe to at least one of {events()}")
    unknown = [e for e in wanted if e not in KNOWN_EVENTS]
    if unknown:
        raise WebhookError(f"this app never emits {unknown} (known: {events()})")

    session = _sys(graph)
    live = [h for h in session.find_entities(
        "content", {"type": RECORD, "account_id": account_id}, limit=100)
        if not h["attrs"].get("disabled")]
    if len(live) >= MAX_HOOKS:
        raise WebhookError(f"{MAX_HOOKS} webhooks is enough — remove one first")

    secret = SECRET_PREFIX + secrets.token_urlsafe(32)
    hook_id = session.create_entity("content", {
        "type": RECORD, "url": url, "events": wanted, "account_id": account_id,
        "secret_hash": hashlib.sha256(secret.encode()).hexdigest(),
        # Stored readable, unlike an API key, and the difference is worth stating: a key is
        # something the *caller* presents, so a hash is enough to check it. A signing secret
        # is something *we* compute with on every delivery, so HMAC needs the real bytes.
        # The hash is kept alongside only so a support question ("is this the secret you
        # gave me?") can be answered without reading the secret back out.
        "secret": secret,
        "disabled": False, "created_at": now_iso(),
        "last_status": "", "failures": 0,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {
        "webhook_id": hook_id, "url": url, "events": wanted,
        "signing_secret": secret,
        "signature_header": SIGNATURE_HEADER,
        "timestamp_header": TIMESTAMP_HEADER,
        "signed_payload": "<timestamp>.<raw body>",
        "store_it_now": "Shown once. Deliveries are signed with it.",
        "delivery": ("At-most-once and synchronous: there is no background worker in this "
                     "app, so a failed delivery is recorded, not retried."),
    }


def listing(graph: Graph, *, account_id: str) -> dict:
    if not account_id:
        raise WebhookError("sign in first")
    rows = _sys(graph).find_entities("content", {"type": RECORD, "account_id": account_id},
                                     limit=100)
    hooks = [{"webhook_id": r["id"], "url": r["attrs"].get("url", ""),
              "events": r["attrs"].get("events", []),
              "disabled": bool(r["attrs"].get("disabled")),
              "last_status": r["attrs"].get("last_status", ""),
              "failures": r["attrs"].get("failures", 0),
              "created_at": r["attrs"].get("created_at", "")}
             for r in rows if not r["attrs"].get("disabled")]
    hooks.sort(key=lambda h: h["created_at"], reverse=True)
    return {"webhooks": hooks, "empty": not hooks, "known_events": events()}


def remove(graph: Graph, webhook_id: str, *, account_id: str,
           source: str = MODULE) -> dict:
    session = _sys(graph)
    row = session.get_entity(webhook_id)
    if row is None or row["attrs"].get("type") != RECORD:
        raise WebhookError("unknown webhook")
    if row["attrs"].get("account_id") != account_id:
        raise WebhookError("that webhook is not yours")
    session.update_entity(webhook_id, {"disabled": True}, source=source)
    return {"removed": True, "webhook_id": webhook_id}


def _post(url: str, body: str, headers: dict) -> int:
    import urllib.request

    from substrate import safefetch

    safefetch.check_url(url)               # re-checked at delivery: DNS can change
    request = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return int(response.status)


def dispatch(graph: Graph, event: str, payload: dict, *, account_id: str = "",
             post=None, source: str = MODULE) -> dict:
    """Send one event to every subscriber of it. Never raises.

    A webhook target being down must not fail the user action that produced the event —
    somebody's meetup does not fail to be created because their own integration is broken.
    """
    if event not in KNOWN_EVENTS:
        return {"event": event, "sent": 0, "status": "unknown_event"}

    session = _sys(graph)
    body = json.dumps({"event": event, "sent_at": now_iso(), "data": payload},
                      sort_keys=True)
    timestamp = str(int(time.time()))
    sent = failed = 0
    results = []

    for row in session.find_entities("content", {"type": RECORD}, limit=500):
        attrs = row["attrs"]
        if attrs.get("disabled") or event not in (attrs.get("events") or []):
            continue
        if account_id and attrs.get("account_id") != account_id:
            continue
        headers = {
            "Content-Type": "application/json",
            TIMESTAMP_HEADER: timestamp,
            SIGNATURE_HEADER: sign(str(attrs.get("secret", "")), body, timestamp),
            "User-Agent": "LifeOS-Webhooks/1.0",
        }
        try:
            status = (post or _post)(attrs.get("url", ""), body, headers)
            ok = 200 <= status < 300
        except Exception as exc:
            status, ok = f"error: {type(exc).__name__}", False

        sent += 1 if ok else 0
        failed += 0 if ok else 1
        session.update_entity(row["id"], {
            "last_status": str(status),
            "failures": 0 if ok else int(attrs.get("failures", 0)) + 1,
        }, source=source)
        session.create_entity("content", {
            "type": DELIVERY, "webhook_id": row["id"], "event": event,
            "status": str(status), "ok": ok, "created_at": now_iso(),
        }, source=source, owner_id=SYSTEM_OWNER)
        results.append({"webhook_id": row["id"], "status": str(status), "ok": ok})

    return {"event": event, "sent": sent, "failed": failed, "results": results,
            "retried": False}


def deliveries(graph: Graph, *, account_id: str, limit: int = 50) -> dict:
    """What actually happened. The screen an integrator needs when nothing is arriving."""
    session = _sys(graph)
    mine = {r["id"] for r in session.find_entities(
        "content", {"type": RECORD, "account_id": account_id}, limit=100)}
    rows = [r for r in session.find_entities("content", {"type": DELIVERY},
                                             limit=MAX_DELIVERIES_KEPT * 2)
            if r["attrs"].get("webhook_id") in mine]
    items = [{"webhook_id": r["attrs"].get("webhook_id", ""),
              "event": r["attrs"].get("event", ""),
              "status": r["attrs"].get("status", ""), "ok": bool(r["attrs"].get("ok")),
              "at": r["attrs"].get("created_at", "")} for r in rows]
    items.sort(key=lambda d: d["at"], reverse=True)
    return {"deliveries": items[:limit], "empty": not items}
