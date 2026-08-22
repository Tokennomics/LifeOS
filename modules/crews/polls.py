"""Crew polls — the thing a group chat does badly, done once.

`/crews/polls/vote` accepted any string as an option, defaulted it to "Bouldering & Drinks"
when the caller sent nothing, returned `voted: True`, and stored nothing. There was no poll:
no question, no options, no other voters, and no way to see a result. Voting was a toast.

A poll is a small object with strict edges, because every one of those edges is somewhere
the group-chat version goes wrong:

- **Votes are for an option that exists.** The prop took free text, so two people voting for
  the same thing spelled differently would have been two answers. You vote by index into the
  options the poll was opened with, or not at all.
- **One vote each, changeable.** Re-voting replaces your previous answer rather than adding
  to it. A poll where the loudest person can vote twice is not a poll.
- **Members only, both to vote and to read.** A crew's plans are not public, and a poll that
  a stranger can read tells them who is where on Friday.
- **Who voted for what is visible.** This is a deliberate choice against a secret ballot: a
  crew deciding between bouldering and dinner needs to know *who* is coming to each, and
  hiding that makes the result unusable for the only thing it is for.
- **It closes.** An open poll with no deadline is a decision nobody makes.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.crews import crews

MODULE = "crews.polls"
SCOPES = {"content:read", "content:write"}
RECORD = "crew_poll"
VOTE = "crew_poll_vote"

MAX_QUESTION = 200
MAX_OPTION = 80
MAX_OPTIONS = 8
MIN_OPTIONS = 2
DEFAULT_HOURS = 48
MAX_HOURS = 24 * 14
MAX_LISTED = 50


class PollError(ValueError):
    """A poll that cannot be opened, voted in or read."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _text(value, cap: int) -> str:
    return str(value or "").strip()[:cap]


def _require_member(graph: Graph, crew_id: str, account_id: str) -> None:
    """Members only — and the refusal is the same one a stranger gets for a crew that does
    not exist, so a poll cannot be used to discover which crews somebody is in."""
    if not account_id:
        raise PollError("sign in first")
    if not crews.is_member(graph, crew_id, account_id):
        raise PollError("no such poll")


def _options(values) -> list[str]:
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, (list, tuple)):
        raise PollError("what are the options?")
    seen, options = set(), []
    for value in values:
        option = _text(value, MAX_OPTION)
        key = option.lower()
        if not option or key in seen:
            continue
        seen.add(key)
        options.append(option)
    if len(options) < MIN_OPTIONS:
        raise PollError(f"a poll needs at least {MIN_OPTIONS} options")
    if len(options) > MAX_OPTIONS:
        raise PollError(f"that is more than {MAX_OPTIONS} options")
    return options


def _open(attrs: dict, now=None) -> bool:
    if attrs.get("closed"):
        return False
    closes = _parse(attrs.get("closes_at", ""))
    return not (closes and closes <= (now or _now()))


def open_poll(graph: Graph, *, crew_id: str, question: str, options,
              account_id: str, handle: str = "", hours: int = DEFAULT_HOURS,
              source: str = MODULE) -> dict:
    """Ask the crew something. Any member can — a poll is not a privilege."""
    crew_id = str(crew_id or "").strip()
    _require_member(graph, crew_id, account_id)
    question = _text(question, MAX_QUESTION)
    if not question:
        raise PollError("what are you asking?")
    choices = _options(options)

    if hours is None:
        hours = DEFAULT_HOURS
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        raise PollError("hours must be a number")
    if hours < 1 or hours > MAX_HOURS:
        raise PollError(f"pick between 1 and {MAX_HOURS} hours")

    poll_id = _sys(graph).create_entity("content", {
        "type": RECORD, "crew_id": crew_id, "question": question, "options": choices,
        "opened_by": account_id, "opened_handle": _text(handle, 80),
        "created_at": now_iso(), "closed": False,
        "closes_at": (_now() + datetime.timedelta(hours=hours)).isoformat(),
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"opened": True, "poll_id": poll_id, "crew_id": crew_id,
            "question": question, "options": choices, "closes_in_hours": hours}


def _poll(graph: Graph, poll_id: str, account_id: str) -> dict:
    row = _sys(graph).get_entity(str(poll_id or "").strip())
    if row is None or row["attrs"].get("type") != RECORD:
        raise PollError("no such poll")
    _require_member(graph, row["attrs"].get("crew_id", ""), account_id)
    return row


def vote(graph: Graph, *, poll_id: str, option, account_id: str, handle: str = "",
         source: str = MODULE) -> dict:
    """Vote by index into the poll's own options. One each, changeable until it closes."""
    row = _poll(graph, poll_id, account_id)
    attrs = row["attrs"]
    if not _open(attrs):
        raise PollError("that poll has closed")

    options = list(attrs.get("options") or [])
    index = _index_of(option, options)

    session = _sys(graph)
    # Re-voting replaces rather than stacks: a poll where the loudest person votes twice is
    # not a poll.
    for previous in session.find_entities(
            "content", {"type": VOTE, "poll_id": row["id"], "account_id": account_id},
            limit=20):
        session.update_entity(previous["id"], {"superseded": True}, source=source)

    vote_id = session.create_entity("content", {
        "type": VOTE, "poll_id": row["id"], "crew_id": attrs.get("crew_id", ""),
        "account_id": account_id, "handle": _text(handle, 80),
        "option_index": index, "option": options[index],
        "created_at": now_iso(), "superseded": False,
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"voted": True, "vote_id": vote_id, "poll_id": row["id"],
            "option": options[index], **results(graph, poll_id=row["id"],
                                                account_id=account_id)}


def _index_of(option, options: list[str]) -> int:
    """An option that is on the poll, or nothing.

    The prop took free text and echoed it back, so two people picking the same thing spelled
    differently would have been two different answers — and a vote for an option nobody
    offered would have counted.
    """
    if isinstance(option, bool):
        raise PollError("which option?")
    if isinstance(option, int):
        index = option
    else:
        text = _text(option, MAX_OPTION)
        if not text:
            raise PollError("which option?")
        if text.isdigit():
            index = int(text)
        else:
            lowered = [o.lower() for o in options]
            if text.lower() not in lowered:
                raise PollError("that is not one of the options")
            return lowered.index(text.lower())
    if not 0 <= index < len(options):
        raise PollError("that is not one of the options")
    return index


def _live_votes(graph: Graph, poll_id: str) -> list[dict]:
    return [row for row in _sys(graph).find_entities(
        "content", {"type": VOTE, "poll_id": poll_id}, limit=MAX_LISTED * 8)
        if not row["attrs"].get("superseded")]


def results(graph: Graph, *, poll_id: str, account_id: str) -> dict:
    """The counts, and who is behind each one."""
    row = _poll(graph, poll_id, account_id)
    attrs = row["attrs"]
    options = list(attrs.get("options") or [])

    tally = [{"option": option, "index": i, "votes": 0, "voters": []}
             for i, option in enumerate(options)]
    yours = None
    for vote_row in _live_votes(graph, row["id"]):
        v = vote_row["attrs"]
        index = v.get("option_index")
        if not isinstance(index, int) or not 0 <= index < len(tally):
            continue
        tally[index]["votes"] += 1
        # Deliberately not a secret ballot: a crew choosing between bouldering and dinner
        # needs to know who is coming to each.
        tally[index]["voters"].append(v.get("handle") or "someone")
        if v.get("account_id") == account_id:
            yours = index

    total = sum(t["votes"] for t in tally)
    leaders = [t for t in tally if t["votes"] == max((x["votes"] for x in tally), default=0)]
    return {"poll_id": row["id"], "crew_id": attrs.get("crew_id", ""),
            "question": attrs.get("question", ""), "options": options,
            "tally": tally, "total_votes": total,
            "your_vote": yours,
            "open": _open(attrs), "closes_at": attrs.get("closes_at", ""),
            # A tie is a tie. Picking one of them to call the winner is how a poll starts
            # lying about what the crew said.
            "leading": [t["option"] for t in leaders] if total else [],
            "tied": total > 0 and len(leaders) > 1,
            "empty": total == 0}


def close_poll(graph: Graph, *, poll_id: str, account_id: str,
               source: str = MODULE) -> dict:
    """Close it early. Whoever opened it, or a crew admin."""
    row = _poll(graph, poll_id, account_id)
    attrs = row["attrs"]
    if attrs.get("opened_by") != account_id and \
            not crews.is_admin(graph, attrs.get("crew_id", ""), account_id):
        raise PollError("only whoever opened it, or an admin, can close it")
    if not _open(attrs):
        return {"closed": True, "poll_id": row["id"], "already": True}
    _sys(graph).update_entity(row["id"], {"closed": True, "closed_at": now_iso()},
                              source=source)
    return {"closed": True, "poll_id": row["id"],
            **results(graph, poll_id=row["id"], account_id=account_id)}


def for_crew(graph: Graph, *, crew_id: str, account_id: str,
             include_closed: bool = False, limit: int = MAX_LISTED) -> dict:
    """Open polls in a crew you are in, newest first."""
    crew_id = str(crew_id or "").strip()
    _require_member(graph, crew_id, account_id)
    now = _now()
    items = []
    for row in _sys(graph).find_entities("content", {"type": RECORD, "crew_id": crew_id},
                                         limit=MAX_LISTED * 4):
        attrs = row["attrs"]
        live = _open(attrs, now)
        if not live and not include_closed:
            continue
        votes = _live_votes(graph, row["id"])
        items.append({"poll_id": row["id"], "question": attrs.get("question", ""),
                      "options": list(attrs.get("options") or []),
                      "opened_by_handle": attrs.get("opened_handle") or "someone",
                      "created_at": attrs.get("created_at", ""),
                      "closes_at": attrs.get("closes_at", ""), "open": live,
                      "total_votes": len(votes),
                      "you_voted": any(v["attrs"].get("account_id") == account_id
                                       for v in votes)})
    items.sort(key=lambda p: p["created_at"], reverse=True)
    return {"crew_id": crew_id, "polls": items[:limit], "empty": not items}
