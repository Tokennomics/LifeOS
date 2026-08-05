"""G3 — block and report that work outside a crew, and outlive it.

`modules/crews.block` and `modules/crews.report` are both crew-scoped: they take a
`crew_id`, they check crew admin, and a report about a person is filed against the crew it
happened in. That is right for a crew and wrong for a date. A crew is a group with an
admin; a date is one person alone with someone they met online, and the thing worth
reporting usually happens *after* everyone has left the crew's context — sometimes after
the crew itself is gone.

So blocks and reports here are account-to-account. They live in the system-owned slice,
which means neither party can edit or delete the other's, and they survive any crew.

**Blocks are stored as a symmetric digest of the pair, not as two names.** Enforcement
only ever asks "are these two blocked from each other", which a digest answers exactly as
well; storing it that way means the block table is not also a readable list of who avoids
whom. Sorting the pair before hashing makes one row cover both directions, which is the
correct semantics anyway — a block is mutual invisibility, not a one-way mute.

**Reports are deliberately NOT blinded.** A moderation queue that a human cannot read is
not a moderation queue. Filing one also blocks the pair immediately, so the reporter is
protected at the moment they ask rather than whenever the queue is next serviced — the
ROADMAP's test is whether a solo operator can actually service this, and the answer has to
hold on a day nobody services it.
"""

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "dating"
SCOPES = {"content:read", "content:write"}

OPEN = "open"


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _pair_key(a: str, b: str) -> str:
    """A symmetric, unguessable handle for an unordered pair of accounts."""
    from modules.security import crypto_tokens
    return crypto_tokens.sign_payload(
        {"ns": "dating/block/v1", "pair": sorted([str(a), str(b)])})


def _me(graph: Graph, account_id: str | None) -> str:
    who = str(account_id or graph.default_owner or "").strip()
    if not who:
        raise ValueError("account_id required")
    return who


def _block_row(graph: Graph, key: str):
    hits = _sys(graph).find_entities(
        "content", {"type": "dating_block", "pair_key": key}, limit=1)
    return hits[0] if hits else None


# ---- blocking ---------------------------------------------------------------

def block(graph: Graph, subject_account_id: str, account_id: str | None = None,
          source: str = MODULE) -> dict:
    """Stop two accounts from ever matching. Either side may do it, unilaterally."""
    me = _me(graph, account_id)
    subject = str(subject_account_id or "").strip()
    if not subject:
        raise ValueError("subject_account_id required")
    if subject == me:
        raise ValueError("you cannot block yourself")

    key = _pair_key(me, subject)
    existing = _block_row(graph, key)
    if existing:
        _sys(graph).update_entity(existing["id"], {"active": True}, source=source)
        return {"blocked": True, "pair_key": key}
    _sys(graph).create_entity("content", {
        "type": "dating_block", "pair_key": key, "active": True, "created_at": now_iso(),
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"blocked": True, "pair_key": key}


def unblock(graph: Graph, subject_account_id: str, account_id: str | None = None,
            source: str = MODULE) -> dict:
    me = _me(graph, account_id)
    key = _pair_key(me, str(subject_account_id or "").strip())
    existing = _block_row(graph, key)
    if not existing or existing["attrs"].get("active") is not True:
        return {"blocked": False, "changed": False}
    _sys(graph).update_entity(existing["id"], {"active": False}, source=source)
    return {"blocked": False, "changed": True}


def is_blocked(graph: Graph, a: str, b: str) -> bool:
    row = _block_row(graph, _pair_key(a, b))
    return bool(row and row["attrs"].get("active") is True)


# ---- reporting --------------------------------------------------------------

def report(graph: Graph, subject_account_id: str, reason: str,
           account_id: str | None = None, context: str = "",
           source: str = MODULE) -> dict:
    """File a report about another account. Blocks the pair as a side effect.

    `context` is free text precisely because there may not be a crew, an event or any
    other structured thing to point at — "walked me to a taxi I hadn't called" needs
    somewhere to go.
    """
    me = _me(graph, account_id)
    subject = str(subject_account_id or "").strip()
    if not subject:
        raise ValueError("subject_account_id required")
    if subject == me:
        raise ValueError("you cannot report yourself")
    reason = str(reason or "").strip()[:1000]
    if not reason:
        raise ValueError("a report needs a reason")

    report_id = _sys(graph).create_entity("content", {
        "type": "dating_report", "reporter_id": me, "subject_id": subject,
        "reason": reason, "context": str(context or "").strip()[:1000],
        "status": OPEN, "created_at": now_iso(),
    }, source=source, owner_id=SYSTEM_OWNER)

    block(graph, subject, account_id=me, source=source)
    return {"report_id": report_id, "status": OPEN, "blocked": True}


def open_reports(graph: Graph, limit: int = 100) -> list[dict]:
    """The moderation queue. Operator-facing: this is the one place dating data is
    readable in plain text, and it exists so a human can act on it."""
    out = []
    for r in _sys(graph).find_entities("content", {"type": "dating_report"}, limit=limit):
        a = r["attrs"]
        if a.get("status") != OPEN:
            continue
        out.append({"id": r["id"], "reporter_id": a.get("reporter_id"),
                    "subject_id": a.get("subject_id"), "reason": a.get("reason"),
                    "context": a.get("context", ""), "created_at": a.get("created_at")})
    return out


def resolve_report(graph: Graph, report_id: str, action: str = "actioned",
                   source: str = MODULE) -> dict:
    """Close a report. The block stays — resolving the queue item is not a decision to
    put the two people back in front of each other."""
    row = _sys(graph).get_entity(report_id)
    if row is None or row["attrs"].get("type") != "dating_report":
        raise ValueError("unknown report")
    _sys(graph).update_entity(
        report_id, {"status": str(action or "actioned").strip() or "actioned",
                    "resolved_at": now_iso()}, source=source)
    return {"report_id": report_id, "status": action}
