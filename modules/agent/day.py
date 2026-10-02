"""Plan a day out of what is actually on.

"Plan my Saturday in Lisbon" is the agent request that most needs real data. Everything a
plan can honestly contain already exists on the box: public listings (venue feeds and
Ticketmaster, kept fresh by `feeds.autosync`), meetups people proposed in the city room,
and places from OpenStreetMap. What a plan must not contain is anything else: no invented
venue, no invented time, no "sunset drinks at 19:30" that nobody scheduled.

So the shape is fixed and the model's freedom is narrow:

- **Candidates** are rows: events and meetups starting that day in that city, plus places.
  Each carries the id of the row it came from.
- **Your own commitments** that day are read first, and a candidate that overlaps one is
  dropped rather than double-booked.
- **Without a key** the plan is the timed candidates in order, with up to two places for the
  hours around them; a place has no time, because nobody gave it one.
- **With a key** a model chooses and orders from the candidates by id and writes one line
  per stop. An id that is not a candidate is discarded, so the model can leave things out
  but cannot add any.
- **Nothing is booked.** Every stop becomes a pending `add_plan` proposal; approving one
  puts it in your own calendar (and so in the calendar feed). A stop with a ticket link
  keeps it, because buying the ticket is yours to do.
"""

import datetime
import json
import re

from substrate.graph import Graph

MODULE = "agent.day"
MAX_TIMED = 4
MAX_PLACES = 2
PLACE_CATEGORIES = ("coffee", "market", "park", "viewpoint", "gallery")

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_SYSTEM = (
    "You plan one day for a person from a list of candidate stops. Choose and order stops "
    "using ONLY candidate ids from the list; never add a stop, a venue, a time or a detail "
    "that is not in it. Prefer a plan that fits together, and leave things out rather than "
    "cram. For each chosen stop write one short plain sentence on why it fits. No emoji."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "stops": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "why": {"type": "string"}},
            "required": ["id", "why"], "additionalProperties": False}},
        "note": {"type": "string"},
    },
    "required": ["stops", "note"],
    "additionalProperties": False,
}


def resolve_day(word: str, today: datetime.date | None = None) -> datetime.date:
    """today / tonight / tomorrow / a weekday (the next one, today included) / YYYY-MM-DD."""
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    w = str(word or "").strip().lower()
    if w in ("", "today", "tonight", "day"):
        return today
    if w == "tomorrow":
        return today + datetime.timedelta(days=1)
    if w in WEEKDAYS:
        return today + datetime.timedelta(days=(WEEKDAYS.index(w) - today.weekday()) % 7)
    try:
        return datetime.date.fromisoformat(w[:10])
    except ValueError:
        raise ValueError(f"which day is {word!r}? Say today, tomorrow, a weekday or YYYY-MM-DD")


def _parse(stamp) -> datetime.datetime | None:
    try:
        value = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)


def _on(stamp, day: datetime.date) -> bool:
    return str(stamp or "")[:10] == day.isoformat()


def _busy(graph: Graph, day: datetime.date) -> list[tuple]:
    """Your own commitments that day, as (start, end) — the plan must not double-book."""
    out = []
    for ev in graph.session(MODULE, {"events:read"}).find_entities("event", limit=500):
        a = ev["attrs"]
        if a.get("origin") == "feed" or not _on(a.get("start"), day):
            continue
        start = _parse(a.get("start"))
        if not start:
            continue
        end = _parse(a.get("end")) or start + datetime.timedelta(hours=1)
        out.append((start, end, a.get("title", "")))
    return out


def _clashes(start, end, busy) -> str:
    for b_start, b_end, title in busy:
        if start < b_end and b_start < end:
            return title or "something already in your calendar"
    return ""


def candidates(graph: Graph, day: datetime.date, city: str, *,
               account_id: str = "") -> dict:
    """Every row a plan for this day may use, and every row it may not and why."""
    from modules.ai import assist
    from modules.city import places

    from modules.city import meetups, synergy
    from modules.discover import discover

    if not city and account_id:
        city = assist._safely(lambda: synergy.city_for(graph, account_id), "")
    # Not `assist.grounding`: that keeps the 20 soonest, and a plan for Saturday asked on a
    # Monday would only ever see the week's first 20 listings.
    found = assist._safely(lambda: discover.find(graph, city=city, limit=300), {}) if city else {}
    facts = {"events": found.get("events", []) if isinstance(found, dict) else [],
             "meetups": assist._safely(lambda: meetups.listing(
                 graph, city, viewer_id=account_id).get("meetups", []), []) if city else []}
    busy = _busy(graph, day)
    timed, clashed = [], []

    rows = [("event", e.get("id", ""), e.get("title", ""), e.get("start", ""), e.get("end", ""),
             e.get("venue") or e.get("place", ""), e.get("url", "")) for e in facts["events"]]
    rows += [("meetup", m.get("meetup_id", ""), m.get("title", ""), m.get("starts_at", ""),
              "", m.get("place", ""), "") for m in facts["meetups"]]
    seen = set()
    for kind, ref, title, start_s, end_s, where, url in rows:
        if not ref or ref in seen or not _on(start_s, day):
            continue
        seen.add(ref)
        start = _parse(start_s)
        if not start:
            continue
        end = _parse(end_s) or start + datetime.timedelta(hours=2)
        stop = {"id": ref, "kind": kind, "title": title, "start": start.isoformat(),
                "end": end.isoformat(), "where": where, "url": url}
        clash = _clashes(start, end, busy)
        if clash:
            clashed.append({**stop, "clashes_with": clash})
        else:
            timed.append(stop)
    timed.sort(key=lambda s: s["start"])

    spots = []
    if city:
        for category in PLACE_CATEGORIES:
            listed = assist._safely(lambda c=category: places.listing(graph, city, category=c),
                                    {"places": []})
            for p in listed["places"][:3]:
                if p.get("name"):
                    spots.append({"id": p["place_id"], "kind": "place", "title": p["name"],
                                  "category": p.get("category", ""),
                                  "hours": p.get("opening_hours", "")})
    return {"city": city, "day": day.isoformat(), "timed": timed, "places": spots,
            "clashed": clashed, "busy": [{"title": t, "start": s.isoformat(),
                                         "end": e.isoformat()} for s, e, t in busy]}


def _assembled(c: dict) -> list[dict]:
    stops = [{**s, "why": ""} for s in c["timed"][:MAX_TIMED]]
    if len(stops) < MAX_TIMED:
        used = set()
        for p in c["places"]:
            if len([s for s in stops if s["kind"] == "place"]) >= MAX_PLACES:
                break
            if p["category"] in used:
                continue
            used.add(p["category"])
            stops.append({**p, "why": ""})
    return stops


def plan(graph: Graph, when: str = "today", city: str = "", *, account_id: str = "",
         claude=None, propose: bool = True) -> dict:
    from modules.agent import core

    day = resolve_day(when)
    c = candidates(graph, day, city, account_id=account_id)
    if not c["city"]:
        return {"day": day.isoformat(), "city": "", "stops": [], "proposals": [],
                "empty": True, "assisted": False,
                "suggestion": "Which city? Say \"plan Saturday in Lisbon\", or check in to one."}

    stops, assisted, note = _assembled(c), False, ""
    pool = {s["id"]: s for s in c["timed"] + c["places"]}
    if pool and claude is not None and getattr(claude, "available", False):
        try:
            data = claude.complete_json(_SYSTEM, json.dumps({
                "day": c["day"], "city": c["city"], "already_booked": c["busy"],
                "remembered": [f["text"] for f in core.facts(graph)],
                "candidates": list(pool.values())}), schema=_SCHEMA, max_tokens=1200)
            chosen = [{**pool[s["id"]], "why": core._clean(s.get("why", ""), 200)}
                      for s in data.get("stops", []) if s.get("id") in pool]
            if chosen:
                stops, assisted, note = chosen, True, core._clean(data.get("note", ""), 300)
        except Exception:
            pass

    made = []
    if propose:
        for s in stops:
            args = {"title": s["title"], "day": c["day"], "city": c["city"], "ref": s["id"],
                    "kind": s["kind"], "where": s.get("where", ""), "url": s.get("url", "")}
            if s.get("start"):
                args.update(start=s["start"], end=s.get("end", ""))
            when_label = s["start"][11:16] if s.get("start") else "any time"
            made.append(core.propose(graph, "add_plan", args,
                                     f"{when_label} · {s['title']}"[:200]))

    return {
        "day": c["day"], "city": c["city"], "stops": stops, "proposals": made,
        "clashed": c["clashed"], "empty": not stops, "assisted": assisted, "note": note,
        "suggestion": "" if stops else (
            f"Nothing is listed in {c['city']} for {c['day']} yet. Listings refresh on their "
            "own; a venue's calendar or a meetup in the city room fills it sooner."),
    }


_PLAN = re.compile(
    r"^\s*plan\s+(?:my\s+|the\s+)?(today|tonight|tomorrow|day|" + "|".join(WEEKDAYS) +
    r"|\d{4}-\d{2}-\d{2})(?:\s+in\s+(.+?))?\s*[.?!]?\s*$", re.I)


def match(text: str):
    """(when, city) if this is a plan-a-day request, else None."""
    m = _PLAN.match(str(text or ""))
    return (m.group(1), (m.group(2) or "").strip()) if m else None
