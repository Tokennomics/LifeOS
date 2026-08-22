"""Sending an email, or honestly reporting that we cannot.

This is the first thing in LifeOS that reaches *out* to a paid service, so it is also the
first place the oldest rule in the repo gets awkward: *every feature works with no API key
and improves with one*. An email cannot be delivered without a provider. What "works with no
key" has to mean here is: **nothing raises, nothing hangs, nothing silently pretends**. With
no key configured, `send()` returns `not_configured` and the caller decides what to do — and
what the OTP flow does is put the code in the response, which is exactly right for a
laptop and exactly wrong for a public box. See `otp.request_code`.

Resend is the provider because it is one HTTPS POST with a bearer token — no SMTP, no TLS
negotiation, no port 587 blocked by the host. Adding another provider means adding a
function to `_PROVIDERS`; nothing else changes.

**The key is read from the environment and never logged.** `status()` reports whether a key
exists, never any part of its value.
"""

import json
import os
import urllib.error
import urllib.request

#: The provider's key. No default — an unset key is a configuration state, not an error.
RESEND_KEY_VAR = "LIFEOS_RESEND_KEY"
#: Who mail appears to come from, e.g. "LifeOS <hello@yourdomain.com>". Resend requires the
#: domain to be verified in their dashboard; an unverified sender is rejected at the API.
FROM_VAR = "LIFEOS_MAIL_FROM"

RESEND_ENDPOINT = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 10


def _env(name: str) -> str:
    return str(os.environ.get(name, "") or "").strip()


def configured() -> bool:
    """A provider key *and* a from-address. Either alone cannot deliver anything."""
    return bool(_env(RESEND_KEY_VAR) and _env(FROM_VAR))


def status() -> dict:
    """What the operator needs to fix, without ever echoing the key itself."""
    missing = [name for name in (RESEND_KEY_VAR, FROM_VAR) if not _env(name)]
    return {
        "provider": "resend",
        "configured": not missing,
        "missing": missing,
        "detail": "" if not missing else f"set {' and '.join(missing)} to send email",
    }


def _post_resend(to: str, subject: str, text: str) -> dict:
    payload = json.dumps({
        "from": _env(FROM_VAR), "to": [to], "subject": subject, "text": text,
    }).encode("utf-8")
    request = urllib.request.Request(
        RESEND_ENDPOINT, data=payload, method="POST",
        headers={"Authorization": f"Bearer {_env(RESEND_KEY_VAR)}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8") or "{}")
    return {"sent": True, "status": "sent", "id": body.get("id", "")}


_PROVIDERS = {"resend": _post_resend}


def send(to: str, subject: str, text: str, *, provider: str = "resend") -> dict:
    """Deliver one message. **Never raises** — the result is the report.

    A caller that treats "the mail server is down" as a crash turns a provider outage into a
    500 on sign-in. Every failure mode arrives here as a status string instead: no key, a
    rejected address, a timeout, a 5xx from the provider.
    """
    to = str(to or "").strip()
    if not to:
        return {"sent": False, "status": "invalid_recipient", "detail": "no address given"}
    if not configured():
        return {"sent": False, "status": "not_configured", **status()}

    sender = _PROVIDERS.get(provider)
    if sender is None:
        return {"sent": False, "status": "unknown_provider", "detail": provider}

    try:
        return sender(to, subject, text)
    except urllib.error.HTTPError as exc:
        # The provider's body often says exactly what is wrong ("domain not verified"), and
        # it is the operator's own error text — worth surfacing. It cannot contain the key.
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:                                     # pragma: no cover - defensive
            pass
        return {"sent": False, "status": f"provider_error_{exc.code}", "detail": detail}
    except Exception as exc:                                  # timeout, DNS, TLS, bad JSON
        return {"sent": False, "status": "send_failed", "detail": str(exc)[:200]}
