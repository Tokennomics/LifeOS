"""Anchor outings — the same plan every week, actually written down.

`POST /seeding/anchor-outings` answered `anchors_active: True` for any city with three
outings nobody had arranged — a dawn surf at Carcavelos, a bathhouse in Alfama, a market
cook-off in Ribeira, each with "spots_reserved" — and `steward_guarantee: "Guaranteed Crew
Host Present on Every Anchor"`. No host had agreed to anything, no spot was reserved, and
the three outings were the same on every deployment including ones nowhere near Lisbon.
Somebody could have gone to a beach at 7am for a meetup that existed only in a dict.

The idea underneath is sound and it is how a young city surface stops being empty: a few
plans that repeat, so there is always something on. It just has to be real, which means:

- **Somebody is the organiser, and it is whoever ran this.** `meetups.create` counts the
  organiser as going, so the response says plainly that they are on every one of these.
  That is the honest version of "guaranteed host": a named person who has said they will be
  there, and who can cancel.
- **The outings are supplied by the caller**, never defaulted. The operator running this
  knows their city; this module does not, and the old one proved what happens when it
  pretends to.
- **Recurring is spelled out as rows.** There is no repeat rule in the schema and inventing
  one would mean a listing that shows plans no row backs, so a week's anchor becomes N
  meetups a week apart, each of which can be cancelled on its own.
- **Nothing is reserved.** There are no spots, no capacity and no waiting list anywhere in
  this app.

Every meetup is created through `city.meetups`, so its rules apply unchanged: system-owned,
expiring, rate-limited, and refusing anything further out than `meetups.MAX_DAYS_AHEAD`.
"""

import datetime

from substrate.graph import Graph

from modules.city import chat, meetups

MODULE = "city.anchors"

#: How many weeks of repeats one call may write. Past this, `meetups.MAX_DAYS_AHEAD` starts
#: refusing them one by one anyway, which is a confusing way to hit a limit.
MAX_WEEKS = 8
MAX_OUTINGS = 10

NO_GUARANTEE = ("Nobody is guaranteed to be there. Whoever created these is the organiser "
                "of each one and is counted as going; anyone else has to say so themselves.")
NOTHING_RESERVED = "No spots are held. There is no capacity or booking anywhere in this app."


class AnchorError(ValueError):
    """A set of anchors that cannot be created."""


def _outings(values) -> list[dict]:
    if not isinstance(values, (list, tuple)) or not values:
        raise AnchorError("what is on? pass `outings`, each with a title and a start time")
    if len(values) > MAX_OUTINGS:
        raise AnchorError(f"that is more than {MAX_OUTINGS} outings in one call")
    out = []
    for value in values:
        if not isinstance(value, dict):
            raise AnchorError("each outing is an object with `title` and `starts_at`")
        title = str(value.get("title", "") or "").strip()
        starts_at = str(value.get("starts_at", "") or "").strip()
        if not title:
            raise AnchorError("each outing needs a title")
        if not starts_at:
            raise AnchorError(f"'{title}' needs a `starts_at`")
        out.append({"title": title, "starts_at": starts_at,
                    "place": str(value.get("place", "") or "").strip(),
                    "note": str(value.get("note", "") or "").strip()})
    return out


def _weeks(value) -> int:
    try:
        weeks = int(value or 1)
    except (TypeError, ValueError):
        raise AnchorError("weeks must be a number")
    if not 1 <= weeks <= MAX_WEEKS:
        raise AnchorError(f"between 1 and {MAX_WEEKS} weeks")
    return weeks


def create(graph: Graph, city: str, *, outings, weeks=1, account_id: str,
           handle: str = "", source: str = MODULE) -> dict:
    """Write one meetup per outing per week, and report exactly what was written.

    A failure on one outing does not lose the rest: it is listed under `skipped` with the
    reason `meetups` gave, because "three of four went in, here is the fourth" is more use
    to an operator than a single 400.
    """
    if not str(city or "").strip():
        raise AnchorError("which city?")
    if not account_id:
        raise AnchorError("sign in first")
    planned = _outings(outings)
    weeks = _weeks(weeks)

    created, skipped = [], []
    for outing in planned:
        # The meetups module's own date parser, deliberately: a start it accepts here and
        # refuses one line later would be a confusing way to fail.
        first = meetups._parse(outing["starts_at"])
        if first is None:
            skipped.append({"title": outing["title"], "week": 1,
                            "reason": "when? give a date and time"})
            continue
        for week in range(weeks):
            when = (first + datetime.timedelta(weeks=week)).isoformat()
            try:
                made = meetups.create(graph, city, title=outing["title"],
                                      starts_at=when, place=outing["place"],
                                      note=outing["note"], organiser_id=account_id,
                                      organiser_handle=handle, source=source)
            except meetups.MeetupError as exc:
                skipped.append({"title": outing["title"], "week": week + 1,
                                "starts_at": when, "reason": str(exc)})
                continue
            created.append({"meetup_id": made["meetup_id"], "title": outing["title"],
                            "starts_at": made["starts_at"], "place": outing["place"],
                            "week": week + 1})

    return {"city": chat.slug(city), "weeks": weeks,
            "created": created, "count": len(created),
            "skipped": skipped, "empty": not created,
            "organiser_id": account_id, "organiser_handle": handle,
            "no_guarantee": NO_GUARANTEE, "nothing_reserved": NOTHING_RESERVED,
            "safety_note": meetups.SAFETY_NOTE,
            "suggestion": "" if created else (
                "Nothing was created. Each outing needs a title and a start time within "
                f"{meetups.MAX_DAYS_AHEAD} days.")}
