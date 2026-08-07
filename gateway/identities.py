"""One account, several ways in — password, Google, Apple, email, phone.

The point is access across devices: sign in on a new phone with Apple, and it is the same
graph you had on the old one. That only works if an account is separable from the *way you
prove you own it*, so an account now has many `identity` records pointing at it and the
password is simply one of them.

**The rule that prevents account takeover, stated once: identities are never auto-linked by
email.** It is the obvious convenience — "you already have an account with this address, let
me connect them" — and it is the classic takeover: an attacker registers the victim's
address at a provider with sloppy verification, signs in, and inherits the account. So:

- an `(kind, subject)` pair belongs to **exactly one** account, forever;
- an unrecognised identity creates a **new** account, even when the email matches an
  existing one;
- connecting a second way in is an **explicit act while already signed in** to the account
  you are connecting it to (`link`), which is the only moment we know both sides.

The cost is a user who signs up with email and later taps "Sign in with Google" gets a
second, empty account. That is confusing. It is also recoverable — they sign in the old way
and link — whereas the alternative is not recoverable at all.

**Unlinking cannot lock you out.** Removing the last identity is refused; there has to be
another way in first.
"""

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "identities"
SCOPES = {"content:read", "content:write"}

KINDS = ("password", "google", "apple", "email", "phone")
IDENTITY = "auth_identity"


def _sys(graph: Graph):
    """Identities live in the system slice, like accounts — they are not the user's to edit."""
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _norm(kind: str, subject: str) -> tuple[str, str]:
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"unknown identity kind {kind!r} (known: {', '.join(KINDS)})")
    subject = str(subject or "").strip()
    if not subject:
        raise ValueError("an identity needs a subject")
    # Email is case-insensitive; a provider `sub` and a phone number are not.
    return kind, subject.lower() if kind == "email" else subject


def find(graph: Graph, kind: str, subject: str) -> dict | None:
    """Which account does this identity belong to, if any?"""
    kind, subject = _norm(kind, subject)
    hits = _sys(graph).find_entities(
        "content", {"type": IDENTITY, "kind": kind, "subject": subject}, limit=1)
    if not hits:
        return None
    attrs = hits[0]["attrs"]
    return {"identity_id": hits[0]["id"], "kind": kind, "subject": subject,
            "account_id": attrs.get("account_id"), "linked_at": attrs.get("linked_at", "")}


def for_account(graph: Graph, account_id: str) -> list[dict]:
    """Every way into one account. The subject is returned because it is the user's own —
    their email, their phone, their provider id."""
    out = []
    for row in _sys(graph).find_entities(
            "content", {"type": IDENTITY, "account_id": account_id}, limit=50):
        a = row["attrs"]
        out.append({"identity_id": row["id"], "kind": a.get("kind"),
                    "subject": a.get("subject"), "linked_at": a.get("linked_at", "")})
    return out


def link(graph: Graph, account_id: str, kind: str, subject: str,
         source: str = MODULE) -> dict:
    """Connect a way in to an account that is already yours.

    Refuses if the identity belongs to someone else — silently re-pointing it would hand
    one person's sign-in to another's account, which is the takeover this module exists to
    prevent, arriving through the front door.
    """
    kind, subject = _norm(kind, subject)
    existing = find(graph, kind, subject)
    if existing:
        if existing["account_id"] == account_id:
            return {**existing, "linked": False}
        raise ValueError("that identity is already connected to another account")

    identity_id = _sys(graph).create_entity("content", {
        "type": IDENTITY, "kind": kind, "subject": subject,
        "account_id": account_id, "linked_at": now_iso(),
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"identity_id": identity_id, "kind": kind, "subject": subject,
            "account_id": account_id, "linked": True}


def unlink(graph: Graph, account_id: str, kind: str, subject: str,
           source: str = MODULE) -> dict:
    """Remove a way in — never the last one."""
    kind, subject = _norm(kind, subject)
    existing = find(graph, kind, subject)
    if not existing or existing["account_id"] != account_id:
        raise ValueError("that identity is not connected to this account")
    if len(for_account(graph, account_id)) <= 1:
        raise ValueError("that is the only way into this account — add another first")
    _sys(graph).delete_entity(existing["identity_id"], source=source)
    return {"unlinked": True, "kind": kind, "subject": subject}


def sign_in(graph: Graph, kind: str, subject: str, *, handle_hint: str = "",
            ttl_hours: int | None = None, source: str = MODULE) -> dict:
    """Sign in with a verified identity, creating the account on first sight.

    The caller is responsible for having *verified* the identity — a provider signature, or
    a one-time code that was actually delivered. This function does not check that, because
    it cannot: it only knows what it is told. Every call site is a place to look twice.
    """
    from gateway import accounts

    kind, subject = _norm(kind, subject)
    existing = find(graph, kind, subject)
    created = False

    if existing:
        account_id = existing["account_id"]
        account = _sys(graph).get_entity(account_id)
        if account is None:                      # the account was erased; the identity is a stub
            _sys(graph).delete_entity(existing["identity_id"], source=source)
            existing, account = None, None

    if not existing:
        handle = accounts.available_handle(graph, handle_hint or _handle_from(kind, subject))
        account = accounts.register_external(graph, handle, source=source)
        account_id = account["account_id"]
        link(graph, account_id, kind, subject, source=source)
        created = True

    session = accounts.mint_session(graph, account_id, ttl_hours=ttl_hours, source=source)
    return {**session, "account_id": account_id, "created": created,
            "identity": {"kind": kind, "subject": subject}}


def _handle_from(kind: str, subject: str) -> str:
    """A first-guess handle. Never the raw phone number or provider id — a handle is shown
    to other people in crew rosters, and neither of those is theirs to publish."""
    if kind == "email":
        return subject.split("@")[0][:40]
    if kind == "phone":
        return "friend"
    return kind
