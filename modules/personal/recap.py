"""Your month, your places, your energy — computed from what you actually did.

These three surfaces are the first personal thing a new user sees, and all three were props.
A brand-new account with an empty graph was told it had **12 real-world meetups, 34 kudos,
48.5 focus hours and a "Crag Pioneer" badge in Lisbon** — and two different accounts got
byte-identical "personal" statistics, because the numbers were literals in the handler.

That is worse for the product than having no feature at all. A stat about *me* that is
obviously not about me doesn't read as a placeholder; it reads as the whole app being fake,
and it costs you the parts that genuinely work — capture, the weekend digest, crews, the
city room — because the user has already decided not to trust the numbers.

So: everything here is derived from the caller's own graph, and **zero is a real answer.**
An empty month says the month is empty and tells you what would fill it. That is the version
somebody can believe on day one, and the version that is worth something on day thirty.

The rule for anything added here: if it cannot be computed from what the user did, it does
not belong in this module.
"""

import datetime

from substrate.graph import Graph

MODULE = "personal.recap"
SCOPES = {"content:read", "tasks:read", "goals:read", "events:read", "places:read",
          "people:read", "metrics:read", "memories:read", "interests:read"}

#: A stamp is a place you actually went, not a place you looked at.
STAMP_KINDS = ("attended", "went")


def _session(graph: Graph):
    return graph.session(MODULE, SCOPES)


def _parse(stamp: str):
    try:
        when = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _within(stamp: str, since) -> bool:
    when = _parse(stamp)
    return when is not None and when >= since


def monthly(graph: Graph, *, now: str = "") -> dict:
    """The last 30 days, from the graph. No invented figures, and no rounding up.

    The previous version reported `days_shown_up = tasks_done + 3`, which is a real number
    with three added to it — the most quietly dishonest kind of statistic, because it moves
    when you do and is still wrong.
    """
    session = _session(graph)
    stamp = _parse(now) or _now()
    since = stamp - datetime.timedelta(days=30)

    tasks = session.find_entities("task", limit=1000)
    goals = session.find_entities("goal", limit=200)
    events = session.find_entities("event", limit=500)
    captures = session.find_entities("content", limit=1000)

    done = [t for t in tasks
            if t.get("attrs", {}).get("status") == "done"
            and _within(t.get("updated_at") or t.get("created_at", ""), since)]
    goals_done = [g for g in goals if g.get("attrs", {}).get("status") == "done"
                  and _within(g.get("updated_at") or g.get("created_at", ""), since)]
    attended = [e for e in events
                if e.get("attrs", {}).get("status") in ("attended", "went")
                and _within(e.get("attrs", {}).get("start") or e.get("created_at", ""), since)]
    notes = [c for c in captures
             if c.get("attrs", {}).get("type") in ("capture", "note", "journal")
             and _within(c.get("created_at", ""), since)]

    # Days you showed up = distinct days you actually wrote something down or finished
    # something. Counted, never estimated.
    days = {(_parse(row.get("created_at", "")) or stamp).date()
            for row in done + notes + attended}

    places = {}
    for event in attended:
        place = (event.get("attrs", {}).get("place") or "").strip()
        if place:
            places[place] = places.get(place, 0) + 1
    top_place = max(places.items(), key=lambda kv: kv[1])[0] if places else ""

    empty = not (done or goals_done or attended or notes)
    return {
        "window_days": 30,
        "month": stamp.strftime("%B %Y"),
        "days_shown_up": len(days),
        "tasks_done": len(done),
        "goals_done": len(goals_done),
        "meets_attended": len(attended),
        "captures": len(notes),
        "top_place": top_place,
        "empty": empty,
        "share_text": _share_text(stamp, len(days), len(goals_done), len(attended), empty),
        "note": ("Nothing here yet — this fills in as you capture things and go to them."
                 if empty else ""),
    }


def _share_text(stamp, days: int, goals: int, meets: int, empty: bool) -> str:
    if empty:
        return ""          # never offer somebody an empty month to post
    parts = [f"📊 My LifeOS month ({stamp.strftime('%B %Y')})"]
    if days:
        parts.append(f"⚡ {days} day{'s' if days != 1 else ''} shown up")
    if goals:
        parts.append(f"🎯 {goals} goal{'s' if goals != 1 else ''} finished")
    if meets:
        parts.append(f"🧗 {meets} outing{'s' if meets != 1 else ''}")
    return "\n".join(parts)


def passport(graph: Graph, city: str = "") -> dict:
    """Places you actually went, as stamps. Previously three invented Lisbon venues that
    every account on the instance shared."""
    session = _session(graph)
    stamps = []
    for event in session.find_entities("event", limit=500):
        attrs = event.get("attrs", {})
        if attrs.get("status") not in STAMP_KINDS:
            continue
        place = (attrs.get("place") or attrs.get("venue") or "").strip()
        if not place:
            continue
        if city and (attrs.get("city") or "").strip().lower() != city.strip().lower():
            continue
        stamps.append({
            "venue": place,
            "category": (attrs.get("topic") or "").strip(),
            "date": (attrs.get("start") or event.get("created_at", ""))[:10],
            "title": (attrs.get("title") or "").strip(),
        })

    stamps.sort(key=lambda s: s["date"], reverse=True)
    cities = sorted({(e.get("attrs", {}).get("city") or "").strip()
                     for e in session.find_entities("event", limit=500)
                     if e.get("attrs", {}).get("status") in STAMP_KINDS
                     and (e.get("attrs", {}).get("city") or "").strip()})

    return {
        "city": city or (cities[0] if cities else ""),
        "cities": cities,
        "stamps_count": len(stamps),
        "stamps": stamps[:50],
        "empty": not stamps,
        "note": ("No stamps yet. Mark an outing as attended and the place lands here."
                 if not stamps else ""),
    }


def social_battery(graph: Graph, *, now: str = "") -> dict:
    """How much you have been around people lately, and what that suggests.

    The honest version of what was a hardcoded 82%. It reports what it counted and what it
    inferred from it, separately, so the number is auditable rather than oracular — and when
    there is nothing to count it says `unknown` rather than picking a cheerful figure.
    """
    session = _session(graph)
    stamp = _parse(now) or _now()
    since = stamp - datetime.timedelta(days=14)

    events = session.find_entities("event", limit=500)
    recent = [e for e in events
              if e.get("attrs", {}).get("status") in STAMP_KINDS
              and _within(e.get("attrs", {}).get("start") or e.get("created_at", ""), since)]
    upcoming = [e for e in events
                if (parsed := _parse(e.get("attrs", {}).get("start", ""))) is not None
                and parsed > stamp]

    if not recent and not upcoming:
        return {
            "state": "unknown",
            "recent_outings": 0,
            "upcoming_outings": 0,
            "window_days": 14,
            "recommendation": "Nothing logged yet — mark an outing as attended and this "
                              "starts telling you something.",
        }

    # Deliberately coarse. Three buckets is the most this evidence can honestly support,
    # and a percentage would imply a precision that is not there.
    count = len(recent)
    if count == 0:
        state, advice = "quiet", "It has been a quiet fortnight. One low-key thing might be enough."
    elif count <= 3:
        state, advice = "steady", "A steady stretch. Room for one more if something appeals."
    else:
        state, advice = "full", f"{count} outings in two weeks. A night in is a reasonable call."

    return {
        "state": state,
        "recent_outings": count,
        "upcoming_outings": len(upcoming),
        "window_days": 14,
        "recommendation": advice,
    }
