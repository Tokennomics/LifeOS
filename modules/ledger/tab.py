"""The shared tab — who owes whom, recorded, and settled between two real accounts.

Four endpoints claimed to handle money between friends and not one of them wrote a row.
`/ledger/quick-split` divided a number by another number and handed back a
`revolut.me` link with the amount in the query string — a link to somebody else's payment
service, for an account nobody had connected. `/ledger/settle-up` reported a net balance of
€22.50 owed to "Elena R." and "Alex M." on a brand-new account. `/ledger/tip` and
`/ledger/gift-coffee` returned `tipped: True` and a voucher code — `GIFT-FLATWHITE-99`, the
same code every time, redeemable nowhere.

That is the worst thing in the repo to fake. A wrong number about money between friends
does not get shrugged off the way a wrong venue does.

**This app moves no money, and says so on every response.** What it does instead is the part
that actually causes the arguments: keeping track. One person pays for dinner, the tab
records what each person owes them, both sides can see it, and either can mark it settled
when the cash or the transfer happens somewhere else.

- **Both parties can read every entry.** System-owned and addressed, like kudos, for the
  same reason: a debt only one side can see is not a shared tab, it is a private file on
  somebody.
- **Cents, never floats.** Money is stored as whole cents. A tab that accumulates
  floating-point error is a tab that eventually tells two friends different numbers.
- **The odd cents stay with whoever paid.** Splitting €10 three ways cannot give three
  people €3.33 and lose a penny, so the payer absorbs the remainder. It is the only split
  that adds back up to what actually left their account.
- **Currencies never mix.** A balance is per counterparty *per currency*. Summing EUR and
  GBP into one number is how a tab becomes wrong without anybody noticing.
- **A tip is an IOU.** With no payment rails, "I sent you €3.50" is a lie and "I owe you
  €3.50" is true. The coffee you promised someone is the same object as the dinner they
  covered — it just points the other way.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "ledger.tab"
SCOPES = {"content:read", "content:write"}
RECORD = "tab_entry"

SPLIT = "split"
IOU = "iou"
SETTLEMENT = "settlement"
KINDS = (SPLIT, IOU, SETTLEMENT)

MAX_PARTICIPANTS = 30
MAX_CENTS = 100_000_000        # a million in whatever currency; past this it is a typo
MAX_TEXT = 200
MAX_LISTED = 200

NO_MONEY = ("Nothing is transferred. This records what is owed so both of you can see the "
            "same number — settle it however you already do.")


class TabError(ValueError):
    """Something that cannot be split, promised or settled."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _text(value, cap: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:cap]


def _cents(value) -> int:
    """Money in, whole cents out. The only place a float is allowed near a balance."""
    if value is None or str(value).strip() == "":
        raise TabError("how much?")
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise TabError("amount must be a number")
    if amount != amount or amount in (float("inf"), float("-inf")):
        raise TabError("amount must be a number")
    if amount <= 0:
        raise TabError("amount must be more than zero")
    cents = int(round(amount * 100))
    if cents <= 0:
        raise TabError("amount must be more than zero")
    if cents > MAX_CENTS:
        raise TabError("that amount looks like a typo")
    return cents


def _money(cents: int) -> float:
    return round(cents / 100, 2)


def _currency(value) -> str:
    code = str(value or "").strip().upper() or "EUR"
    if not (len(code) == 3 and code.isalpha()):
        raise TabError("currency is a three-letter code, like EUR")
    return code


def _people(values, *, exclude: str) -> list[str]:
    """The other people on this tab — deduplicated, in a stable order, never you."""
    if isinstance(values, str):
        values = [v for v in values.split(",")]
    if not isinstance(values, (list, tuple)):
        raise TabError("who was there?")
    seen, people = set(), []
    for value in values:
        person = str(value or "").strip()
        if not person or person == exclude or person in seen:
            continue
        seen.add(person)
        people.append(person)
    if not people:
        raise TabError("who else was there? A split needs somebody to split with.")
    if len(people) > MAX_PARTICIPANTS:
        raise TabError(f"that is more than {MAX_PARTICIPANTS} people")
    return people


def _write(graph: Graph, *, kind: str, debtor: str, creditor: str, cents: int,
           currency: str, note: str = "", item: str = "", group_id: str = "",
           source: str = MODULE) -> str:
    return _sys(graph).create_entity("content", {
        "type": RECORD, "kind": kind,
        "debtor": debtor, "creditor": creditor,
        "cents": cents, "currency": currency,
        "note": note, "item": item, "group_id": group_id,
        "created_at": now_iso(),
    }, source=source, owner_id=SYSTEM_OWNER)


def shares(total_cents: int, people: int) -> list[int]:
    """What each of the others owes. The payer keeps the remainder, so it adds back up.

    Splitting 1000 cents three ways is 333, 333, and 334 for whoever paid — not three
    times 3.33 and a penny that evaporates.
    """
    if people < 1:
        raise TabError("who else was there?")
    base = total_cents // (people + 1)
    return [base] * people


def preview(amount, people_count, currency: str = "EUR") -> dict:
    """The arithmetic with nobody named — a calculator, not a tab.

    The old quick-split took a headcount and a total, and that *is* a useful thing to ask at
    a table before anybody has swapped handles. It survives, and it records nothing, and it
    says which of those two it is: a debt with no name on it has nobody to settle with.
    """
    total = _cents(amount)
    try:
        people = int(people_count)
    except (TypeError, ValueError):
        raise TabError("how many people?")
    if people < 2:
        raise TabError("a split is at least two people")
    if people > MAX_PARTICIPANTS + 1:
        raise TabError(f"that is more than {MAX_PARTICIPANTS + 1} people")
    each = shares(total, people - 1)
    return {"recorded": False, "total": _money(total), "currency": _currency(currency),
            "people": people, "each": _money(each[0]),
            "your_share": _money(total - sum(each)),
            "note": ("Nothing is recorded — name the people to put it on a tab you can "
                     "both see and settle.")}


# ---- writing -----------------------------------------------------------------

def split(graph: Graph, *, account_id: str, participants, amount, currency: str = "EUR",
          note: str = "", source: str = MODULE) -> dict:
    """You paid for something; everybody else owes you their share."""
    if not account_id:
        raise TabError("sign in first")
    people = _people(participants, exclude=account_id)
    total = _cents(amount)
    code = _currency(currency)
    note = _text(note)

    owed = shares(total, len(people))
    group_id = now_iso() + ":" + account_id
    entries, claimed = [], 0
    for person, cents in zip(people, owed):
        if cents <= 0:
            # Splitting 3 cents four ways owes nobody anything. Writing rows of zero would
            # put entries on a tab that can never be settled because there is nothing there.
            continue
        claimed += cents
        entries.append({
            "entry_id": _write(graph, kind=SPLIT, debtor=person, creditor=account_id,
                               cents=cents, currency=code, note=note, group_id=group_id,
                               source=source),
            "person": person, "owes_you": _money(cents), "currency": code})

    return {"split": True, "total": _money(total), "currency": code,
            "people": len(people) + 1, "note": note,
            "your_share": _money(total - claimed),
            "entries": entries, "money_moved": False, "no_money": NO_MONEY}


def iou(graph: Graph, *, account_id: str, to_account: str, amount=None,
        currency: str = "EUR", item: str = "", note: str = "",
        source: str = MODULE) -> dict:
    """You owe somebody — a tip you meant to send, or the coffee you promised them."""
    if not account_id:
        raise TabError("sign in first")
    to_account = str(to_account or "").strip()
    if not to_account:
        raise TabError("who is it for?")
    if to_account == account_id:
        raise TabError("you cannot owe yourself")
    item = _text(item, 80)
    cents = _cents(amount) if str(amount or "").strip() else 0
    if not cents and not item:
        raise TabError("an amount, or what you owe them")
    code = _currency(currency)

    entry_id = _write(graph, kind=IOU, debtor=account_id, creditor=to_account,
                      cents=cents, currency=code, item=item, note=_text(note),
                      source=source)
    return {"recorded": True, "entry_id": entry_id, "to_account": to_account,
            "amount": _money(cents) if cents else None, "item": item,
            "currency": code if cents else "",
            "visible_to_them": True, "money_moved": False,
            "note": ("Recorded as owed, not sent. They can see it, and either of you can "
                     "mark it settled once it actually happens.")}


def settle(graph: Graph, *, account_id: str, counterparty: str, amount=None,
           currency: str = "EUR", note: str = "", source: str = MODULE) -> dict:
    """Mark a debt paid — all of it, or part.

    Refuses to settle more than is owed. A tab that lets you overpay into a negative silently
    reverses who owes whom, which is exactly the confusion the tab exists to prevent.
    """
    if not account_id:
        raise TabError("sign in first")
    counterparty = str(counterparty or "").strip()
    if not counterparty:
        raise TabError("settling with whom?")
    if counterparty == account_id:
        raise TabError("you cannot settle with yourself")
    code = _currency(currency)

    standing = _net(graph, account_id).get((counterparty, code), 0)
    if standing >= 0:
        raise TabError("you do not owe them anything in " + code)
    outstanding = -standing
    cents = _cents(amount) if str(amount or "").strip() else outstanding
    if cents > outstanding:
        raise TabError(f"you only owe {_money(outstanding)} {code}")

    entry_id = _write(graph, kind=SETTLEMENT, debtor=account_id, creditor=counterparty,
                      cents=cents, currency=code, note=_text(note), source=source)
    left = outstanding - cents
    return {"settled": True, "entry_id": entry_id, "counterparty": counterparty,
            "amount": _money(cents), "currency": code,
            "still_owed": _money(left), "clear": left == 0,
            "money_moved": False, "no_money": NO_MONEY}


def dispute(graph: Graph, *, account_id: str, entry_id: str, reason: str = "",
            source: str = MODULE) -> dict:
    """Reject an entry somebody put on your tab.

    Without this the tab is a harassment vector: anybody can assert that anybody else owes
    them a thousand euros, and the other person can see it and do nothing about it. Being
    visible is not the same as being agreed to.

    Only the side the entry counts *against* can dispute it — the debtor on a split or an
    IOU, and the creditor on a settlement, since a settlement is the payer claiming a debt
    is discharged. A disputed entry stops counting toward any balance and stays on both
    histories, marked. Nothing is deleted: an entry that vanishes is an argument with no
    record, which is the thing this module exists to prevent.
    """
    if not account_id:
        raise TabError("sign in first")
    row = _sys(graph).get_entity(str(entry_id or "").strip())
    if row is None or row["attrs"].get("type") != RECORD:
        raise TabError("no such entry")
    attrs = row["attrs"]
    against = attrs.get("creditor") if attrs.get("kind") == SETTLEMENT else attrs.get("debtor")
    if against != account_id:
        # Including the other party to it: you cannot withdraw a claim by disputing it.
        raise TabError("that entry is not yours to dispute")
    if attrs.get("disputed"):
        return {"disputed": True, "entry_id": row["id"], "already": True}

    _sys(graph).update_entity(row["id"], {"disputed": True, "disputed_by": account_id,
                                          "disputed_reason": _text(reason, 200),
                                          "disputed_at": now_iso()}, source=source)
    return {"disputed": True, "entry_id": row["id"],
            "note": ("It no longer counts toward either balance, and it stays on both "
                     "histories so there is a record of the disagreement.")}


# ---- reading -----------------------------------------------------------------

def _mine(graph: Graph, account_id: str) -> list[dict]:
    """Every entry with you on one side of it. Never anybody else's tab."""
    session = _sys(graph)
    rows = session.find_entities("content", {"type": RECORD, "debtor": account_id},
                                 limit=MAX_LISTED * 4)
    rows += session.find_entities("content", {"type": RECORD, "creditor": account_id},
                                  limit=MAX_LISTED * 4)
    seen, unique = set(), []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        unique.append(row)
    return unique


def _net(graph: Graph, account_id: str) -> dict:
    """Cents per (counterparty, currency). Positive means they owe you."""
    totals: dict[tuple[str, str], int] = {}
    for row in _mine(graph, account_id):
        attrs = row["attrs"]
        cents = int(attrs.get("cents", 0) or 0)
        if not cents or attrs.get("disputed"):
            continue
        code = attrs.get("currency", "") or "EUR"
        debtor, creditor = attrs.get("debtor", ""), attrs.get("creditor", "")
        # A settlement runs the other way: paying somebody reduces what you owe them, so it
        # carries the opposite sign to the debt that created it.
        sign = -1 if attrs.get("kind") == SETTLEMENT else 1
        if creditor == account_id:
            key = (debtor, code)
            totals[key] = totals.get(key, 0) + sign * cents
        elif debtor == account_id:
            key = (creditor, code)
            totals[key] = totals.get(key, 0) - sign * cents
    return totals


def balances(graph: Graph, *, account_id: str) -> dict:
    """What you are owed and what you owe, per person, per currency."""
    if not account_id:
        raise TabError("sign in first")
    items = []
    for (person, code), cents in _net(graph, account_id).items():
        if cents == 0:
            continue
        items.append({"counterparty": person, "currency": code,
                      "net": _money(abs(cents)),
                      "they_owe_you": cents > 0,
                      "direction": "they owe you" if cents > 0 else "you owe them"})
    items.sort(key=lambda b: (-b["net"], b["counterparty"]))
    owed_to_you = {}
    you_owe = {}
    for item in items:
        bucket = owed_to_you if item["they_owe_you"] else you_owe
        bucket[item["currency"]] = round(bucket.get(item["currency"], 0) + item["net"], 2)
    return {"balances": items, "empty": not items,
            "owed_to_you": owed_to_you, "you_owe": you_owe,
            "money_moved": False, "no_money": NO_MONEY}


def entries(graph: Graph, *, account_id: str, counterparty: str = "",
            limit: int = MAX_LISTED) -> dict:
    """The history behind the number, so a balance is never something to take on faith."""
    if not account_id:
        raise TabError("sign in first")
    counterparty = str(counterparty or "").strip()
    items = []
    for row in _mine(graph, account_id):
        attrs = row["attrs"]
        debtor, creditor = attrs.get("debtor", ""), attrs.get("creditor", "")
        other = creditor if debtor == account_id else debtor
        if counterparty and other != counterparty:
            continue
        cents = int(attrs.get("cents", 0) or 0)
        items.append({"entry_id": row["id"], "kind": attrs.get("kind", ""),
                      "counterparty": other, "disputed": bool(attrs.get("disputed")),
                      "yours_to_dispute": (
                          (attrs.get("creditor") if attrs.get("kind") == SETTLEMENT
                           else attrs.get("debtor")) == account_id
                          and not attrs.get("disputed")),
                      "amount": _money(cents) if cents else None,
                      "currency": attrs.get("currency", "") if cents else "",
                      "item": attrs.get("item", ""), "note": attrs.get("note", ""),
                      "you_owe": debtor == account_id,
                      "created_at": attrs.get("created_at", "")})
    items.sort(key=lambda e: e["created_at"], reverse=True)
    return {"entries": items[:limit], "total": len(items), "empty": not items,
            "counterparty": counterparty}
