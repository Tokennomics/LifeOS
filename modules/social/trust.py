"""Vouches — one named person saying they know another. Not a score, and not verification.

`/trust/web-of-trust` returned `trust_verified: True` and `trust_score: "98/100 (Tier-1
Community Vouched)"` for any name you sent, with a vouching chain naming people who do not
exist ("Vouched by Marco, Co-Living Host, 14 verified dinners"), a
`COMMUNITY_VERIFIED_BADGE`, and a `privacy_standard` of "Zero-Knowledge Proof (No phone
number or government ID exposed)" — describing a cryptographic scheme that is not
implemented anywhere in this repo.

**This is the most dangerous prop left**, for the same reason SafeWalk was: it changes how
somebody behaves toward a stranger. A person who reads "98/100, community verified, three
mutual vouches" meets differently from a person who knows nothing about who they are meeting.
It said that about everyone, including whoever you had just typed in.

What is real and worth keeping is the thing underneath: **somebody you know can say, on the
record, that they know this person.** That is genuinely useful and it is not a score.

- **A vouch is a claim by a named account**, readable by both sides, and nothing else. This
  app verifies no identity, checks no document, and says so on every response.
- **No number.** A count of vouches is a count; there is no index, no tier and no badge. A
  trust score is the karma score under another name, and that was removed on its merits.
- **Who vouched is shown.** An anonymous vouch is worth nothing — the value is entirely in
  knowing *whose* word it is, so you can weigh it yourself.
- **You cannot vouch for yourself**, and a vouch can be withdrawn, because people change
  their minds and a vouch that cannot be taken back is one nobody should give.
- **Nothing here is safety advice.** The disclaimer is part of the response, not a footnote.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "social.trust"
SCOPES = {"content:read", "content:write"}
RECORD = "vouch"

MAX_NOTE = 200
MAX_LISTED = 100

NOT_VERIFICATION = (
    "A vouch is one person saying they know another. This app verifies no identity, checks "
    "no document and runs no background check — weigh who vouched, not how many did.")


class TrustError(ValueError):
    """A vouch that cannot be given or read."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _text(value, cap: int = MAX_NOTE) -> str:
    return str(value or "").strip()[:cap]


def vouch(graph: Graph, *, account_id: str, for_account: str, note: str = "",
          handle: str = "", source: str = MODULE) -> dict:
    """Say on the record that you know somebody."""
    if not account_id:
        raise TrustError("sign in first")
    for_account = str(for_account or "").strip()
    if not for_account:
        raise TrustError("vouch for whom?")
    if for_account == account_id:
        raise TrustError("you cannot vouch for yourself")

    session = _sys(graph)
    for row in session.find_entities(
            "content", {"type": RECORD, "from_account": account_id,
                        "for_account": for_account}, limit=10):
        if not row["attrs"].get("withdrawn"):
            # Re-vouching updates the note rather than stacking, so a count of vouches is a
            # count of people rather than a count of clicks.
            session.update_entity(row["id"], {"note": _text(note),
                                              "updated_at": now_iso()}, source=source)
            return {"vouched": True, "vouch_id": row["id"], "already": True,
                    "for_account": for_account, "no_score": True,
                    "disclaimer": NOT_VERIFICATION}

    vouch_id = session.create_entity("content", {
        "type": RECORD, "from_account": account_id, "from_handle": _text(handle, 80),
        "for_account": for_account, "note": _text(note),
        "created_at": now_iso(), "withdrawn": False,
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"vouched": True, "vouch_id": vouch_id, "for_account": for_account,
            "visible_to_them": True,
            # The old response carried `trust_score: "98/100"`. There is no number here.
            "no_score": True,
            "disclaimer": NOT_VERIFICATION}


def withdraw(graph: Graph, *, account_id: str, for_account: str,
             source: str = MODULE) -> dict:
    """Take it back. A vouch that cannot be withdrawn is one nobody should give."""
    if not account_id:
        raise TrustError("sign in first")
    session = _sys(graph)
    withdrawn = 0
    for row in session.find_entities(
            "content", {"type": RECORD, "from_account": account_id,
                        "for_account": str(for_account or "").strip()}, limit=10):
        if not row["attrs"].get("withdrawn"):
            session.update_entity(row["id"], {"withdrawn": True,
                                              "withdrawn_at": now_iso()}, source=source)
            withdrawn += 1
    if not withdrawn:
        raise TrustError("you have not vouched for them")
    return {"withdrawn": True, "for_account": for_account}


def _live(graph: Graph, query: dict) -> list:
    return [row for row in _sys(graph).find_entities("content", {"type": RECORD, **query},
                                                     limit=MAX_LISTED * 2)
            if not row["attrs"].get("withdrawn")]


def about(graph: Graph, *, account_id: str, subject: str = "") -> dict:
    """Who has vouched for somebody, by name.

    Returns people, never a rating. The old endpoint answered "98/100 (Tier-1 Community
    Vouched)" about a stranger, which is precisely the sentence that makes somebody drop
    their guard.
    """
    if not account_id:
        raise TrustError("sign in first")
    subject = str(subject or "").strip() or account_id

    rows = _live(graph, {"for_account": subject})
    vouchers = [{"from_account": r["attrs"].get("from_account", ""),
                 "handle": r["attrs"].get("from_handle") or "someone",
                 "note": r["attrs"].get("note", ""),
                 "created_at": r["attrs"].get("created_at", "")} for r in rows]
    vouchers.sort(key=lambda v: v["created_at"], reverse=True)

    # Whether *you* are among them, which is the only part of this that is about the reader.
    yours = any(v["from_account"] == account_id for v in vouchers)
    return {"subject": subject, "vouchers": vouchers, "count": len(vouchers),
            "you_vouched": yours, "empty": not vouchers,
            "no_score": True, "verified": False,
            "disclaimer": NOT_VERIFICATION,
            "suggestion": ("Nobody has vouched for them here. That is not a red flag and "
                           "not a green one — it is simply nothing."
                           if not vouchers else "")}


def given(graph: Graph, *, account_id: str) -> dict:
    """Who you have vouched for."""
    if not account_id:
        raise TrustError("sign in first")
    rows = _live(graph, {"from_account": account_id})
    items = [{"for_account": r["attrs"].get("for_account", ""),
              "note": r["attrs"].get("note", ""),
              "created_at": r["attrs"].get("created_at", "")} for r in rows]
    items.sort(key=lambda v: v["created_at"], reverse=True)
    return {"given": items, "count": len(items), "empty": not items,
            "disclaimer": NOT_VERIFICATION}


def in_common(graph: Graph, *, account_id: str, subject: str) -> dict:
    """People who have vouched for both of you — a real answer to "who do we both know?".

    The prop asserted "3 Mutual Friends in ConnectOS Web of Trust" for any pair. This is the
    computable version of that idea, and it is often zero, which is the useful part.
    """
    if not account_id:
        raise TrustError("sign in first")
    subject = str(subject or "").strip()
    if not subject or subject == account_id:
        raise TrustError("in common with whom?")
    mine = {r["attrs"].get("from_account") for r in _live(graph, {"for_account": account_id})}
    theirs = {r["attrs"].get("from_account") for r in _live(graph, {"for_account": subject})}
    shared = sorted(x for x in (mine & theirs) if x)
    return {"subject": subject, "in_common": shared, "count": len(shared),
            "no_score": True, "disclaimer": NOT_VERIFICATION}
