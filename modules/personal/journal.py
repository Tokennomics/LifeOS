"""A day's reflection, built from what you actually did.

`/journal/daily-reflection-synthesis` is the most brazen prop in the repo, because it does
not invent a venue or a number — it invents *your day*. Send it "Munich" and it tells you,
in the first person, that you watched dawn surfers on the Eisbach wave, shared sourdough
pretzels with new local friends, and heard analog synths at Blitz Club. Send it "Edinburgh"
and you climbed Arthur's Seat in the mist and went to a poetry reading at Typewronger Books.
It then thanks a man called Lukas for a speakeasy passcode.

There was a branch per city and nothing else. Two people in the same city got the same
memories; somebody who had spent the day in bed got them too.

A reflection is worth having and it is entirely constructible from rows this app already
holds — check-ins, meetups, moments, notes, spending. So it is assembled from those, and
when there is nothing it says there is nothing, which is a genuinely useful answer on a quiet day.

- **Every line points at a row.** `sources` names what each part came from, so nothing in a
  reflection is unattributable.
- **No score.** There was a `presence_score: 98.5%` in the export's sample frontmatter. This
  app measures no such thing.
- **A model may phrase it, never populate it.** With a key set, the wording can be smoothed;
  the facts still come from the graph, and `assisted` says which happened.
"""

import datetime

from substrate.graph import Graph

MODULE = "personal.journal"
SCOPES = {"content:read", "events:read", "metrics:read"}

MAX_ITEMS = 40


class JournalError(ValueError):
    """A day that cannot be reflected on."""


def _session(graph: Graph):
    return graph.session(MODULE, SCOPES)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _day_bounds(day: str):
    """The UTC day being reflected on. Empty means today."""
    if str(day or "").strip():
        try:
            start = datetime.datetime.fromisoformat(str(day).strip()[:10]).replace(
                tzinfo=datetime.timezone.utc)
        except ValueError:
            raise JournalError("date should look like 2026-08-15")
    else:
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + datetime.timedelta(days=1)


def _in_day(stamp: str, start, end) -> bool:
    moment = _parse(stamp)
    return bool(moment and start <= moment < end)


def day(graph: Graph, *, account_id: str = "", date: str = "", claude=None) -> dict:
    """What you did on a day, from your own rows. Never from a city.

    The city branch is gone entirely: where you were does not tell anybody what they did,
    and a reflection that reads convincingly while being about nobody is worse than an empty
    one.
    """
    start, end = _day_bounds(date)
    session = _session(graph)
    did, sources = [], []

    for row in session.find_entities("content", {"type": "checkin"}, limit=200):
        attrs = row["attrs"]
        if _in_day(attrs.get("created_at", ""), start, end):
            where = attrs.get("place") or attrs.get("city") or "somewhere"
            did.append(f"Went to {where}")
            sources.append({"kind": "check-in", "id": row["id"]})

    for row in session.find_entities("content", {"type": "city_moment"}, limit=200):
        attrs = row["attrs"]
        if attrs.get("account_id") == account_id and \
                _in_day(attrs.get("created_at", ""), start, end):
            did.append(f"Posted: {attrs.get('caption', '')}")
            sources.append({"kind": "moment", "id": row["id"]})

    notes = []
    for row in session.find_entities("content", {"type": "reflection"}, limit=200):
        attrs = row["attrs"]
        if _in_day(attrs.get("created_at", ""), start, end):
            notes.append(attrs.get("note", ""))
            sources.append({"kind": "reflection", "id": row["id"]})

    spent = []
    for row in session.find_entities("metric", {"type": "spend"}, limit=300):
        attrs = row["attrs"]
        if _in_day(attrs.get("created_at", "") or attrs.get("month", ""), start, end):
            spent.append({"amount": attrs.get("amount", 0),
                          "category": attrs.get("category", "misc")})
            sources.append({"kind": "spend", "id": row["id"]})

    empty = not (did or notes or spent)
    return {
        "date": start.date().isoformat(),
        "did": did[:MAX_ITEMS],
        "notes": notes[:MAX_ITEMS],
        "spent": spent[:MAX_ITEMS],
        # Every line points at a row, so nothing here is unattributable.
        "sources": sources[:MAX_ITEMS * 2],
        "empty": empty,
        "summary": _summary(did, notes, start),
        # There was a `presence_score: 98.5%` in the old export's frontmatter. Nothing in
        # this app measures presence, or anything else about how a day went.
        "no_score": "Nothing here rates your day.",
        "suggestion": ("Nothing is recorded for this day. Checking in somewhere, or writing "
                       "a line, is what makes one of these worth reading later."
                       if empty else ""),
        **_assist(claude),
    }


def _summary(did, notes, start) -> str:
    """One plain sentence, assembled — never invented.

    It used to be a paragraph of travel writing ("A day sculpted by the rush of glacial
    river rapids…") that was the same for everybody who named the same city.
    """
    if not did and not notes:
        return ""
    parts = []
    if did:
        parts.append(f"{len(did)} thing{'' if len(did) == 1 else 's'} recorded")
    if notes:
        parts.append(f"{len(notes)} note{'' if len(notes) == 1 else 's'} written")
    return f"{start.strftime('%A %d %B')}: " + ", ".join(parts) + "."


def _assist(claude) -> dict:
    from modules.ai import assist
    return assist.available(claude)


def week(graph: Graph, *, account_id: str = "", days: int = 7, claude=None) -> dict:
    """The same, over several days — the shape a week had, from rows."""
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise JournalError("days must be a number")
    days = max(1, min(days, 31))
    today = datetime.datetime.now(datetime.timezone.utc).date()
    entries = []
    for back in range(days):
        stamp = (today - datetime.timedelta(days=back)).isoformat()
        one = day(graph, account_id=account_id, date=stamp, claude=claude)
        if not one["empty"]:
            entries.append({"date": one["date"], "did": one["did"],
                            "notes": one["notes"]})
    return {"days": days, "entries": entries, "empty": not entries,
            "suggestion": ("Nothing recorded in the last "
                           f"{days} days." if not entries else ""),
            **_assist(claude)}
