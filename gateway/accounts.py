"""Accounts — identity for the gateway: registration, login, revocable sessions.

This is the piece the cross-user features have been waiting on. Design notes, because
auth is the wrong place to be clever:

- **Credentials never live in plaintext.** Passwords are PBKDF2-HMAC-SHA256 with a
  per-account random salt; tokens are random 256-bit strings and only their SHA-256 is
  stored, so a database read cannot impersonate anyone.
- **Sessions are stored, therefore revocable.** Stateless signed tokens would be less
  work, but "revocation must be first-class" is a standing rule here — an agent or a
  phone that goes missing has to be cuttable at once.
- **No new tables.** The v0 schema is final, so accounts and sessions are `content`
  entities owned by a fixed SYSTEM owner, which also keeps them out of every user's
  own owner-scoped view.
- **Each account gets its own `owner_id`**, which is what scopes their slice of the
  graph. That is the seam multi-user isolation hangs off.
- No user enumeration: a bad handle and a bad password fail identically.
"""

import datetime
import hashlib
import hmac
import secrets

from substrate import SYSTEM_OWNER, new_id, now_iso
from substrate.graph import Graph

SCOPES = {"content:read", "content:write"}
MODULE = "accounts"

ITERATIONS = 200_000
SALT_BYTES = 16
TOKEN_BYTES = 32
DEFAULT_TTL_HOURS = 24 * 30

MIN_PASSWORD = 8


def _sys(graph: Graph):
    """A session over the system-owned slice, whatever the caller's own scope is."""
    system = Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER)
    return system.session(MODULE, SCOPES)


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _norm_handle(handle: str) -> str:
    return str(handle or "").strip().lower()[:80]


def _find_account(session, handle: str):
    hits = session.find_entities("content", {"type": "account", "handle": handle}, limit=1)
    return hits[0] if hits else None


def accounts_exist(graph: Graph) -> bool:
    """False keeps the gateway in its original single-user mode (no accounts, no login)."""
    return bool(_sys(graph).find_entities("content", {"type": "account"}, limit=1))


def register(graph: Graph, handle: str, password: str, source: str = MODULE) -> dict:
    handle = _norm_handle(handle)
    if not handle:
        raise ValueError("a handle is required")
    if not password or len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    session = _sys(graph)
    if _find_account(session, handle):
        raise ValueError("that handle is taken")

    salt = secrets.token_bytes(SALT_BYTES).hex()
    owner_id = new_id()
    account_id = session.create_entity("content", {
        "type": "account", "handle": handle, "owner_id": owner_id,
        "salt": salt, "password_hash": _hash_password(password, salt),
        "iterations": ITERATIONS, "created_at": now_iso(),
    }, source=source)
    return {"account_id": account_id, "handle": handle, "owner_id": owner_id}


def login(graph: Graph, handle: str, password: str, ttl_hours: int = DEFAULT_TTL_HOURS,
          source: str = MODULE) -> dict:
    """Verify credentials and mint a session token. The token is returned ONCE."""
    session = _sys(graph)
    account = _find_account(session, _norm_handle(handle))
    # Same failure for unknown handle and wrong password — no enumeration.
    if account is None:
        raise ValueError("invalid handle or password")
    a = account["attrs"]
    expected = a.get("password_hash", "")
    actual = _hash_password(password or "", a.get("salt", "00"))
    if not hmac.compare_digest(expected, actual):
        raise ValueError("invalid handle or password")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires = (datetime.datetime.now(datetime.timezone.utc)
               + datetime.timedelta(hours=max(1, ttl_hours))).isoformat()
    session_id = session.create_entity("content", {
        "type": "auth_session", "token_hash": _hash_token(token),
        "account_id": account["id"], "owner_id": a.get("owner_id"), "handle": a.get("handle"),
        "created_at": now_iso(), "expires_at": expires, "revoked": False,
    }, source=source)
    return {"token": token, "session_id": session_id, "handle": a.get("handle"),
            "owner_id": a.get("owner_id"), "expires_at": expires}


def resolve(graph: Graph, token: str) -> dict | None:
    """Token -> caller, or None if unknown, revoked or expired."""
    if not token:
        return None
    session = _sys(graph)
    hits = session.find_entities(
        "content", {"type": "auth_session", "token_hash": _hash_token(token)}, limit=1)
    if not hits:
        return None
    s = hits[0]["attrs"]
    if s.get("revoked"):
        return None
    expires = s.get("expires_at", "")
    if expires and expires < now_iso():
        return None
    return {"session_id": hits[0]["id"], "account_id": s.get("account_id"),
            "owner_id": s.get("owner_id"), "handle": s.get("handle")}


def logout(graph: Graph, token: str, source: str = MODULE) -> dict:
    """Revoke one session immediately."""
    caller = resolve(graph, token)
    if caller is None:
        return {"revoked": False}
    _sys(graph).update_entity(caller["session_id"], {"revoked": True}, source=source)
    return {"revoked": True, "session_id": caller["session_id"]}


def revoke_all(graph: Graph, account_id: str, source: str = MODULE) -> dict:
    """Cut every session for an account — the 'my phone is gone' button."""
    session = _sys(graph)
    count = 0
    for s in session.find_entities("content", {"type": "auth_session", "account_id": account_id},
                                   limit=500):
        if not s["attrs"].get("revoked"):
            session.update_entity(s["id"], {"revoked": True}, source=source)
            count += 1
    return {"account_id": account_id, "revoked": count}


def sessions(graph: Graph, account_id: str, limit: int = 100) -> list[dict]:
    """Active sessions for an account — never exposes tokens or their hashes."""
    session = _sys(graph)
    out = []
    for s in session.find_entities("content", {"type": "auth_session", "account_id": account_id},
                                   limit=limit):
        a = s["attrs"]
        if a.get("revoked") or (a.get("expires_at") and a["expires_at"] < now_iso()):
            continue
        out.append({"session_id": s["id"], "created_at": a.get("created_at"),
                    "expires_at": a.get("expires_at")})
    return out
