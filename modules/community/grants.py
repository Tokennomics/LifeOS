"""A proposal for money a community might one day put somewhere. Nobody's money moves.

`POST /community/micro-grants` answered `grant_voted: True`, `grant_status:
"FUNDED_AND_APPROVED"`, "€1,450.00 community fund pool" and 48 votes — for any project
string, on an instance with no fund, no votes and no accounts. Somebody could reasonably
have read that as their neighbourhood project being funded and gone and ordered the timber.

That is the same class of statement as a receipt, so it is built the way `ledger/tab.py`
builds one:

- **Whole cents, never floats, one currency per proposal.** The amount parser is imported
  from the tab rather than written again — a second money parser in a repo is a second set
  of rounding rules, and they diverge.
- **A proposal is a proposal.** `approved: False` and `money_moved: False` are on every
  response, always, because there is no fund to approve it from and no rail to pay it with.
  Nothing in this module can set `approved` to True; approving would mean somebody actually
  holding money, and this deployment has no processor.
- **There is no pool, so no pool is reported.** The prop's `community_fund_pool` was the
  most quoted number in it. What can be counted is what has been *asked for*, which is the
  sum of the open proposals, and it is labelled as that.
- **No votes.** There is no voting system here and inventing one would be inventing a
  mandate. A proposal is listed with who proposed it and that is all.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat
# One money parser in this repo, not two. `tab` already refuses floats, zero, infinities and
# typo-sized amounts, and stores whole cents; a second copy here would drift from it.
from modules.ledger.tab import _cents, _currency, _money

MODULE = "community.grants"
SCOPES = {"content:read", "content:write"}
RECORD = "grant_proposal"

MAX_PROJECT = 120
MAX_NOTE = 500
MAX_LISTED = 100
MAX_PER_WINDOW = 5
WINDOW_MINUTES = 60

NO_MONEY = ("Nothing is transferred and nothing is held. This records what somebody asked "
            "for, so a community can discuss it somewhere money actually changes hands.")
NOT_APPROVED = ("A proposal, not a decision. There is no fund here and no processor "
                "connected, so nothing in this app can approve or pay one.")


class GrantError(ValueError):
    """A proposal that cannot be recorded."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        when = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def propose(graph: Graph, city: str, *, project: str, amount, currency: str = "EUR",
            note: str = "", account_id: str, handle: str = "",
            source: str = MODULE) -> dict:
    """Record an ask. The project name and the amount are required — the prop defaulted
    both, so an empty body funded a surfboard rescue stand in Carcavelos."""
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise GrantError("which city?")
    if not account_id:
        raise GrantError("sign in first")
    project = str(project or "").strip()[:MAX_PROJECT]
    if not project:
        raise GrantError("what is the project?")
    try:
        cents = _cents(amount)
        code = _currency(currency)
    except ValueError as exc:                    # TabError is a ValueError
        raise GrantError(str(exc))

    now = _now()
    session = _sys(graph)
    recent = [row for row in session.find_entities(
        "content", {"type": RECORD, "city": room, "proposed_by": account_id}, limit=100)
        if (made := _parse(row["attrs"].get("created_at"))) is not None
        and made > now - datetime.timedelta(minutes=WINDOW_MINUTES)]
    if len(recent) >= MAX_PER_WINDOW:
        raise GrantError("that is a lot of proposals at once — give it an hour")

    proposal_id = session.create_entity("content", {
        "type": RECORD, "city": room, "city_label": str(city or "").strip()[:80],
        "project": project, "amount_cents": cents, "currency": code,
        "note": str(note or "").strip()[:MAX_NOTE],
        "proposed_by": account_id, "proposed_by_handle": str(handle or "")[:80],
        "created_at": now_iso(), "withdrawn": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"proposed": True, "proposal_id": proposal_id, "city": room,
            "project": project, "amount": _money(cents), "amount_cents": cents,
            "currency": code, "proposed_by": account_id,
            "proposed_by_handle": str(handle or "")[:80],
            "approved": False, "money_moved": False,
            "not_approved": NOT_APPROVED, "no_money": NO_MONEY}


def _render(row: dict, viewer_id: str) -> dict:
    attrs = row["attrs"]
    cents = int(attrs.get("amount_cents") or 0)
    return {"proposal_id": row["id"], "project": attrs.get("project", ""),
            "amount": _money(cents), "amount_cents": cents,
            "currency": attrs.get("currency", ""), "note": attrs.get("note", ""),
            "proposed_by": attrs.get("proposed_by", ""),
            "proposed_by_handle": attrs.get("proposed_by_handle") or "someone",
            "created_at": attrs.get("created_at", ""),
            "approved": False, "money_moved": False,
            "yours": bool(viewer_id) and attrs.get("proposed_by") == viewer_id}


def listing(graph: Graph, city: str, *, viewer_id: str = "",
            limit: int = MAX_LISTED) -> dict:
    """Everything asked for in this city, newest first, with the total asked.

    The total is a sum of rows and is labelled `asked_for`, not a balance: nobody holds it.
    Currencies are never added together — a per-currency total is the only one that is
    arithmetically meaningful, the same rule the tab keeps.
    """
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise GrantError("which city?")

    rows = [row for row in _sys(graph).find_entities(
        "content", {"type": RECORD, "city": room}, limit=MAX_LISTED * 4)
        if not row["attrs"].get("withdrawn")]
    rows.sort(key=lambda r: str(r["attrs"].get("created_at", "")), reverse=True)
    proposals = [_render(row, viewer_id) for row in rows[:limit]]

    asked: dict = {}
    for proposal in proposals:
        code = proposal["currency"]
        asked[code] = asked.get(code, 0) + proposal["amount_cents"]

    return {"city": room, "proposals": proposals, "count": len(proposals),
            "empty": not proposals,
            "asked_for": [{"currency": code, "amount": _money(cents),
                           "amount_cents": cents} for code, cents in sorted(asked.items())],
            "pool": None,
            "no_pool": ("There is no community fund on this deployment. `asked_for` is the "
                        "sum of what people have proposed, not money anybody holds."),
            "money_moved": False, "no_money": NO_MONEY, "not_approved": NOT_APPROVED,
            "suggestion": "" if proposals else (
                "Nobody has proposed anything in this city yet. Anyone signed in can, with "
                "`POST /v1/community/micro-grants`.")}


def withdraw(graph: Graph, proposal_id: str, *, account_id: str,
             source: str = MODULE) -> dict:
    """Take back your own ask."""
    session = _sys(graph)
    row = session.get_entity(proposal_id)
    if row is None or row["attrs"].get("type") != RECORD:
        raise GrantError("unknown proposal")
    if row["attrs"].get("proposed_by") != account_id:
        raise GrantError("only whoever proposed it can withdraw it")
    session.update_entity(proposal_id, {"withdrawn": True}, source=source)
    return {"withdrawn": True, "proposal_id": proposal_id, "money_moved": False}
