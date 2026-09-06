"""One-time codes: proving somebody controls an email address.

This is the seam `identities.link()` has been refusing to let anyone through since it was
written — `email` and `phone` are in `NEEDS_PROOF`, and until now nothing in the API could
set `verified=True`. This module is the proof. It unblocks three things at once: email
sign-in, linking an address to an existing account, and password reset.

**A six-digit code has a million values, so the code itself is not the security.** Guessing
one is trivial if you are allowed to guess. The defences are, in order of how much work they
do:

1. **An attempt cap per code** (`MAX_ATTEMPTS`). Five wrong guesses burns the code. This is
   the one that matters — without it, a million requests is an afternoon.
2. **A short expiry** (`TTL_MINUTES`), which bounds the window for everything else.
3. **Single use.** A verified code is consumed, so a code read over someone's shoulder after
   they have used it is worthless.
4. **An issuance cap per address** (`MAX_PER_WINDOW`). Without it, anyone who knows an
   address can use this endpoint to mail-bomb it, and our sending domain wears the
   reputation damage.

Codes are stored salted and hashed. That is worth doing and worth being honest about: it
does not defend the code against someone who can read the database, because a million
candidates is nothing to hash. What it defends against is the code leaking into somewhere a
database row gets copied to — a backup, a log line, an export — and still being usable.

**Requesting a code never reveals whether the address is known.** The response is identical
for an address with an account and one without. Otherwise this endpoint is an oracle for
"does this person use LifeOS", which for a dating-adjacent app is exactly the question users
are relying on us not to answer.
"""

import datetime
import hashlib
import hmac
import secrets

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "auth.otp"
SCOPES = {"content:read", "content:write"}
RECORD = "auth_otp"

CODE_DIGITS = 6
TTL_MINUTES = 10
MAX_ATTEMPTS = 5
#: Issuance cap per address, and the window it applies over.
MAX_PER_WINDOW = 5
WINDOW_MINUTES = 60

#: What a code is for. A code minted to sign in must not be spendable to link an address to
#: somebody else's account, so the purpose is part of what gets verified.
PURPOSES = ("sign_in", "link", "reset")


class OtpError(ValueError):
    """A code that cannot be issued or cannot be accepted."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _normalise(address: str) -> str:
    address = str(address or "").strip().lower()
    # Deliberately shallow: an address is valid if a provider accepts it, and every regex
    # that tries to be clever here rejects somebody's real address. The only thing worth
    # refusing is what cannot be an address at all.
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        raise OtpError("that does not look like an email address")
    if len(address) > 254:
        raise OtpError("that address is too long")
    return address


def _check_purpose(purpose: str) -> str:
    purpose = str(purpose or "").strip().lower()
    if purpose not in PURPOSES:
        raise OtpError(f"unknown purpose {purpose!r} (known: {', '.join(PURPOSES)})")
    return purpose


def _hash(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _live_codes(graph: Graph, address: str, purpose: str) -> list[dict]:
    return _sys(graph).find_entities(
        "content", {"type": RECORD, "address": address, "purpose": purpose}, limit=50)


def request_code(graph: Graph, address: str, purpose: str = "sign_in", *,
                 send: bool = True, source: str = MODULE) -> dict:
    """Mint a code, store its hash, and try to deliver it.

    Returns the same shape whether or not the address is known to us — see the module
    docstring. `delivered` says whether a provider accepted the message; when no provider is
    configured the plaintext code comes back in `code` so that a laptop install is usable,
    and the caller is responsible for not exposing that on a public box. `/v1/auth/email`
    only passes it through when the gateway is not in production.
    """
    from modules.auth import mailer

    address = _normalise(address)
    purpose = _check_purpose(purpose)
    session = _sys(graph)
    now = _now()

    recent = [row for row in _live_codes(graph, address, purpose)
              if (issued := _parse(row["attrs"].get("issued_at"))) is not None
              and issued > now - datetime.timedelta(minutes=WINDOW_MINUTES)]
    if len(recent) >= MAX_PER_WINDOW:
        raise OtpError(
            f"too many codes requested for that address — wait {WINDOW_MINUTES} minutes")

    # Supersede anything outstanding: two live codes for one address means the attempt cap
    # is really 5 x N, and a user who taps "resend" expects the newest code to be the one
    # that works.
    for row in _live_codes(graph, address, purpose):
        if not row["attrs"].get("consumed"):
            session.update_entity(row["id"], {"consumed": True, "superseded": True},
                                  source=source)

    code = "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))
    salt = secrets.token_hex(16)
    session.create_entity("content", {
        "type": RECORD, "address": address, "purpose": purpose,
        "code_hash": _hash(code, salt), "salt": salt,
        "issued_at": now_iso(),
        "expires_at": (now + datetime.timedelta(minutes=TTL_MINUTES)).isoformat(),
        "attempts": 0, "consumed": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    delivery = {"sent": False, "status": "not_sent"}
    if send:
        delivery = mailer.send(
            address, "Your LifeOS sign-in code",
            f"Your code is {code}\n\n"
            f"It expires in {TTL_MINUTES} minutes and can be used once.\n"
            f"If you did not ask for this, you can ignore this email — "
            f"nobody can sign in without the code.")

    result = {"requested": True, "address": address, "purpose": purpose,
              "expires_in_minutes": TTL_MINUTES, "delivered": bool(delivery.get("sent")),
              "delivery_status": delivery.get("status", "")}
    if not delivery.get("sent"):
        # No provider (or a provider that failed): hand the code back so the flow is still
        # completable. The gateway decides whether the caller may see this.
        result["code"] = code
    return result


def verify_code(graph: Graph, address: str, code: str, purpose: str = "sign_in", *,
                source: str = MODULE) -> dict:
    """Spend a code. Returns `{"verified": True, "address": ...}` or raises `OtpError`.

    Every failure says the same thing — "that code is not valid" — rather than
    distinguishing wrong-code from expired from never-issued. The distinctions are all
    useful to an attacker and none of them help a user, who retries or asks for a new code
    either way.
    """
    address = _normalise(address)
    purpose = _check_purpose(purpose)
    code = str(code or "").strip()
    session = _sys(graph)
    generic = OtpError("that code is not valid — ask for a new one")

    candidates = [row for row in _live_codes(graph, address, purpose)
                  if not row["attrs"].get("consumed")]
    if not candidates:
        raise generic

    row = max(candidates, key=lambda r: str(r["attrs"].get("issued_at", "")))
    attrs = row["attrs"]

    expires = _parse(attrs.get("expires_at"))
    if expires is None or _now() > expires:
        session.update_entity(row["id"], {"consumed": True, "expired": True}, source=source)
        raise generic

    attempts = int(attrs.get("attempts") or 0) + 1
    # compare_digest on the hashes: the codes are equal-length digits so timing leaks
    # nothing here, but the habit is the point — the next thing compared may not be.
    if not hmac.compare_digest(_hash(code, str(attrs.get("salt", ""))),
                               str(attrs.get("code_hash", ""))):
        session.update_entity(
            row["id"],
            {"attempts": attempts, "consumed": attempts >= MAX_ATTEMPTS},
            source=source)
        raise generic

    session.update_entity(row["id"], {"attempts": attempts, "consumed": True,
                                      "verified_at": now_iso()}, source=source)
    return {"verified": True, "address": address, "purpose": purpose}
