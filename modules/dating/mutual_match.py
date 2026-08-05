"""Phase 3b — mutual-consent, activity-based matching.

THE INVARIANT: dating interest is never visible to a non-match. Not by listing, not by id,
not through the feed, not by asking for `visibility=public`, and not by writing yourself a
grant.

**Why the first version could not work, and why the obvious fix is worse.** It asked
`find_entities` for the other person's `dating_intent`. `find_entities` is owner-scoped, so
it always returned nothing and every match was `is_mutual: False` — inert rather than
leaky, but broken. The two existing cross-owner reads are both wrong here: `find_public`
publishes to the world by design, which is the exact opposite of the invariant, and
`get_if_granted` needs a grant that neither side can have *before* the match — the grant is
supposed to be the consequence of matching, not its precondition. Reaching for either one
is how "invisible until mutual" quietly becomes "visible with a low rank".

**The shape that does work: a blinded rendezvous.** Nobody reads anyone's intent. Each side
publishes an opaque digest of *its own* declaration — an HMAC of `(from, to, activity)`
under the server signing key — and to learn whether interest is mutual you compute the
digest the other side *would* have published and ask whether that exact string exists. You
can only compute it for a pair you already name, so:

  - a non-match learns nothing, because there is nothing to read: the published row holds a
    64-character digest and no account id, no target, no activity;
  - the surface cannot be enumerated into a list of who is looking, because the rows are
    owned by the system account rather than by their author — the only thing a full scan
    yields is a count;
  - guessing is not a way in: without `LIFEOS_SIGNING_KEY` the digest cannot be computed at
    all, which is also why `gate.availability()` reports an unset key as "unavailable"
    rather than letting the module run in a weakened mode.

The private `dating_intent` stays in the author's own owner-scoped slice, where it was
always safe, and is never the thing anyone else queries.

**Withdrawal is unilateral and immediate.** Un-publishing your own digest ends the match
from your side alone; the other party's next check simply fails to find it. There is no
"unmatch request" for anyone to decline.
"""

import datetime

from substrate import SYSTEM_OWNER
from substrate.graph import Graph
from modules.dating import gate, safety

SCOPES = {"content:read", "content:write", "people:read"}
MODULE = "dating"

HANDSHAKE = "dating_handshake"
INTENT = "dating_intent"


def _today() -> str:
    """Handshakes carry a DATE, not a timestamp.

    They are the one publicly readable row in the module, and `find_public` orders by
    `created_at` — so a microsecond-resolution field on them is a global activity log of
    "somebody declared dating interest at 21:03:44.118", which correlates against any other
    public signal (a crew join, an event RSVP) to re-identify the author of a row that was
    blinded precisely so it couldn't be. A day is all the display needs.

    Residual, stated rather than papered over: an adversary polling `find_public` in a tight
    loop still observes *arrival order* regardless of what precision is stored. Closing that
    needs batching or jitter on publication, which is not worth its complexity before there
    are real users. Day precision removes the stored handle, which is the part that persists.
    """
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _sys(graph: Graph):
    """Handshakes are system-owned so that a full scan of them names nobody."""
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _rendezvous(from_account: str, to_account: str, activity: str) -> str:
    """The digest `from_account` publishes to declare interest in `to_account` at
    `activity`. Directional: A→B and B→A are different strings, so publishing your own
    never reveals whether the other exists."""
    from modules.security import crypto_tokens
    return crypto_tokens.sign_payload({
        "ns": "dating/rendezvous/v1",
        "from": str(from_account), "to": str(to_account), "activity": str(activity),
    })


def _my_handshake(graph: Graph, rk: str):
    """Find one's own handshake through the system slice — including a withdrawn one,
    which `find_public` deliberately cannot see."""
    hits = _sys(graph).find_entities("content", {"type": HANDSHAKE, "rk": rk}, limit=1)
    return hits[0] if hits else None


def _published(session, rk: str) -> dict | None:
    """Does this exact digest exist and is it currently published? The only cross-owner
    read in the module, and it can answer nothing except yes/no about a string the caller
    already had to compute."""
    hits = session.find_public("content", {"type": HANDSHAKE, "rk": rk}, limit=1)
    return hits[0] if hits else None


def _me(graph: Graph, account_id: str | None) -> str:
    who = str(account_id or graph.default_owner or "").strip()
    if not who:
        raise ValueError("account_id required")
    return who


def express_interest(graph: Graph, target_account_id: str, activity_id: str,
                     account_id: str | None = None, source: str = MODULE) -> dict:
    """Declare private, activity-scoped interest in another account."""
    gate.require_surface()

    target_account_id = str(target_account_id or "").strip()
    activity_id = str(activity_id or "").strip()
    if not target_account_id:
        raise ValueError("target_account_id required")
    if not activity_id:
        raise ValueError("activity_id required")

    session = graph.session(MODULE, SCOPES)
    me = _me(graph, account_id)
    if target_account_id == me:
        raise ValueError("you cannot express interest in yourself")

    gate.require_adult(graph, me)

    # A block is enforced by publishing nothing, and is reported as an ordinary store.
    # Answering "blocked" here would tell the blocked party that they were blocked, which
    # is the one fact a block exists to withhold.
    blocked = safety.is_blocked(graph, me, target_account_id)

    existing = session.find_entities("content", {
        "type": INTENT, "user_id": me, "target": target_account_id,
        "activity": activity_id}, limit=1)
    if existing:
        intent_id = existing[0]["id"]
        session.update_entity(intent_id, {"withdrawn": False}, source=source)
    else:
        intent_id = session.create_entity("content", {
            "type": INTENT, "user_id": me, "target": target_account_id,
            "activity": activity_id, "visibility": "private", "withdrawn": False,
        }, source=source)

    if blocked:
        return {"intent_id": intent_id, "target_account_id": target_account_id,
                "activity_id": activity_id, "outcome": "stored_privately",
                "is_mutual": False}

    mine = _rendezvous(me, target_account_id, activity_id)
    row = _my_handshake(graph, mine)
    if row is None:
        _sys(graph).create_entity("content", {
            "type": HANDSHAKE, "rk": mine, "visibility": "public",
            "created_at": _today(),
        }, source=source, owner_id=SYSTEM_OWNER)
    elif row["attrs"].get("visibility") != "public":
        _sys(graph).update_entity(row["id"], {"visibility": "public"}, source=source)

    theirs = _published(session, _rendezvous(target_account_id, me, activity_id))
    return {
        "intent_id": intent_id,
        "target_account_id": target_account_id,
        "activity_id": activity_id,
        "outcome": "mutual_match" if theirs else "stored_privately",
        "is_mutual": bool(theirs),
    }


def check_matches(graph: Graph, account_id: str | None = None) -> list[dict]:
    """Verified mutual matches, derived entirely from one's own intents plus a yes/no
    question about each counterpart digest. Reads no one else's data."""
    gate.require_surface()
    session = graph.session(MODULE, SCOPES)
    me = _me(graph, account_id)

    matches = []
    for intent in session.find_entities("content", {"type": INTENT, "user_id": me}, limit=200):
        attrs = intent.get("attrs", {})
        target_id, activity_id = attrs.get("target"), attrs.get("activity")
        if not target_id or not activity_id or attrs.get("withdrawn") is True:
            continue
        if safety.is_blocked(graph, me, target_id):
            continue
        theirs = _published(session, _rendezvous(target_id, me, activity_id))
        if theirs:
            matches.append({
                "match_id": intent["id"],
                "target_account_id": target_id,
                "activity_id": activity_id,
                "matched_at": _matched_at(graph, me, target_id, activity_id, theirs),
            })
    return matches


def _matched_at(graph: Graph, me: str, target_id: str, activity_id: str,
                theirs: dict) -> str:
    """When the match FORMED — the later of the two declarations, so both sides agree.

    Reporting the counterpart's own `created_at` (the first version of this) gave Ana
    Bruno's declaration date and Bruno Ana's: two different answers to one shared question,
    and neither of them the date anything actually happened.
    """
    mine = _my_handshake(graph, _rendezvous(me, target_id, activity_id))
    dates = [d for d in (theirs["attrs"].get("created_at", ""),
                         (mine or {}).get("attrs", {}).get("created_at", "")) if d]
    return max(dates) if dates else ""


def withdraw_interest(graph: Graph, target_account_id: str, activity_id: str,
                      account_id: str | None = None, source: str = MODULE) -> dict:
    """Un-publish one's own declaration. Unilateral, immediate, and needs no agreement:
    the other side's next check finds nothing."""
    gate.require_surface()
    session = graph.session(MODULE, SCOPES)
    me = _me(graph, account_id)
    target_account_id = str(target_account_id or "").strip()
    activity_id = str(activity_id or "").strip()

    row = _my_handshake(graph, _rendezvous(me, target_account_id, activity_id))
    if row is not None and row["attrs"].get("visibility") == "public":
        _sys(graph).update_entity(row["id"], {"visibility": "private"}, source=source)

    for intent in session.find_entities("content", {
            "type": INTENT, "user_id": me, "target": target_account_id,
            "activity": activity_id}, limit=1):
        session.update_entity(intent["id"], {"withdrawn": True}, source=source)

    return {"withdrawn": True, "target_account_id": target_account_id,
            "activity_id": activity_id}
