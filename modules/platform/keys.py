"""API keys that actually open the door.

`POST /developer/keys` returned `los_sk_<uuid4>` and stored nothing. `POST
/developers/api-keys` returned `lifeos_dk_...` with a scope list and a "10,000 req/minute"
rate limit, and stored nothing either. Both look exactly like a credential: the shape is
right, the prefix is right, and somebody would paste one into a script.

That is the worst prop in the repo after SafeWalk, and for the same reason — it is not a
number nobody checks, it is a thing a person acts on. A key that authenticates nothing means
a script that silently 401s, or worse, a person who believes an integration is locked down
because they "revoked" a key that never existed.

The real version is boring and short, which is how credential code should look:

- **The secret is shown once and never stored.** Only a SHA-256 hash goes in the graph,
  alongside a display prefix. A leaked database does not leak working keys, and "show me my
  key again" is answered with "no, issue a new one" — which is the correct answer.
- **Keys are owner-scoped and carry scopes.** A key belongs to the account that issued it
  and can never widen beyond what that account can do; `scopes` narrow it further.
- **Revocation is immediate and real**, because a revocation that does nothing is worse than
  having no revocation at all.
- **Comparison is constant-time.** A hash lookup by prefix and `compare_digest` on the
  digest, so key verification does not leak timing.

Wired into `gateway/auth.py`, so presenting one as a bearer token authenticates the account
that issued it. Without that wiring this module would be the same prop with better prose.
"""

import hashlib
import hmac
import secrets

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "platform.keys"
SCOPES = {"content:read", "content:write"}
RECORD = "api_key"

PREFIX = "los_sk_"
SECRET_BYTES = 32
PREFIX_SHOWN = 12          # `los_sk_` + 5 chars: enough to tell two keys apart in a list
MAX_KEYS = 25
MAX_NAME = 80

# What a key may be scoped to. Deliberately coarse: a permission system nobody understands
# is one everybody grants in full.
KNOWN_SCOPES = ("read", "write")


class KeyError_(ValueError):
    """A key that cannot be issued or revoked."""


def _sys(graph: Graph):
    """System-owned so a key can be looked up before we know whose it is — verification
    happens before any account scope exists."""
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def issue(graph: Graph, name: str, *, account_id: str, owner_id: str = "",
          scopes=None, source: str = MODULE) -> dict:
    """Mint a key. The secret in the response is the only time it exists in readable form."""
    if not account_id:
        raise KeyError_("sign in first")
    name = str(name or "").strip()[:MAX_NAME]
    if not name:
        raise KeyError_("give the key a name you will recognise in six months")

    wanted = [s for s in (scopes or ["read"]) if s in KNOWN_SCOPES]
    if not wanted:
        raise KeyError_(f"scopes must be some of {list(KNOWN_SCOPES)}")

    session = _sys(graph)
    live = [k for k in session.find_entities(
        "content", {"type": RECORD, "account_id": account_id}, limit=200)
        if not k["attrs"].get("revoked")]
    if len(live) >= MAX_KEYS:
        raise KeyError_(f"{MAX_KEYS} live keys is enough — revoke one first")

    secret = PREFIX + secrets.token_urlsafe(SECRET_BYTES)
    key_id = session.create_entity("content", {
        "type": RECORD, "name": name,
        "account_id": account_id, "owner_id": owner_id or account_id,
        "digest": _digest(secret), "shown": secret[:PREFIX_SHOWN],
        "scopes": wanted, "revoked": False,
        "created_at": now_iso(), "last_used_at": "",
    }, source=source, owner_id=SYSTEM_OWNER)

    return {
        "key_id": key_id, "name": name, "scopes": wanted,
        # The one and only time this is readable.
        "secret": secret,
        "shown": secret[:PREFIX_SHOWN],
        "store_it_now": ("This is the only time the key is shown. Only a hash is stored, so "
                         "it cannot be recovered — issue a new one if you lose it."),
    }


def _render(row: dict) -> dict:
    attrs = row["attrs"]
    return {"key_id": row["id"], "name": attrs.get("name", ""),
            "shown": attrs.get("shown", ""), "scopes": attrs.get("scopes", []),
            "revoked": bool(attrs.get("revoked")),
            "created_at": attrs.get("created_at", ""),
            "last_used_at": attrs.get("last_used_at", "")}


def listing(graph: Graph, *, account_id: str, include_revoked: bool = False) -> dict:
    """Your keys, without the secrets — because there are no secrets to show."""
    if not account_id:
        raise KeyError_("sign in first")
    rows = _sys(graph).find_entities("content", {"type": RECORD, "account_id": account_id},
                                     limit=200)
    keys = [_render(r) for r in rows if include_revoked or not r["attrs"].get("revoked")]
    keys.sort(key=lambda k: k["created_at"], reverse=True)
    return {"keys": keys, "empty": not keys,
            "note": "Secrets are hashed and cannot be shown again."}


def revoke(graph: Graph, key_id: str, *, account_id: str, source: str = MODULE) -> dict:
    """Immediate. A revocation that does not take effect is worse than none at all."""
    if not account_id:
        raise KeyError_("sign in first")
    session = _sys(graph)
    row = session.get_entity(key_id)
    if row is None or row["attrs"].get("type") != RECORD:
        raise KeyError_("unknown key")
    # Checked rather than filtered: revoking somebody else's key must be a refusal, not a
    # silent no-op that reads as success.
    if row["attrs"].get("account_id") != account_id:
        raise KeyError_("that key is not yours")
    if row["attrs"].get("revoked"):
        return {"revoked": True, "key_id": key_id, "already": True}
    session.update_entity(key_id, {"revoked": True, "revoked_at": now_iso()}, source=source)
    return {"revoked": True, "key_id": key_id, "already": False}


def verify(graph: Graph, secret: str, *, touch: bool = True,
           source: str = MODULE) -> dict | None:
    """Resolve a presented key to its account, or None.

    Never raises and never explains *why* a key failed — "no such key", "revoked" and
    "malformed" are the same answer to whoever is holding it.
    """
    secret = str(secret or "")
    if not secret.startswith(PREFIX):
        return None

    session = _sys(graph)
    wanted = _digest(secret)
    for row in session.find_entities("content", {"type": RECORD,
                                                 "shown": secret[:PREFIX_SHOWN]}, limit=10):
        attrs = row["attrs"]
        if attrs.get("revoked"):
            continue
        # Constant-time: the prefix already narrowed it, and a timing signal on the digest
        # is the classic way a token check leaks.
        if not hmac.compare_digest(str(attrs.get("digest", "")), wanted):
            continue
        if touch:
            session.update_entity(row["id"], {"last_used_at": now_iso()}, source=source)
        return {"key_id": row["id"], "account_id": attrs.get("account_id", ""),
                "owner_id": attrs.get("owner_id") or attrs.get("account_id", ""),
                "scopes": attrs.get("scopes", []), "name": attrs.get("name", "")}
    return None
