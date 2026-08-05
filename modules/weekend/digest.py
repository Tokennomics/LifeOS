"""The weekend digest — graph flow: what you're already committed to, and what's open.

Answers "what's on this weekend?" from three sources that already exist, rather than a
fourth one nobody maintains:

  1. **Public social events** in the city — `find_public`, so they cross accounts. This is
     the "what's happening" half, and it only contains what people have actually published.
  2. **Your own confirmed plans** — `type: "meet"` written by `coordinate` when a night is
     agreed, plus anything synced in from ICS. Owner-scoped, never shared, and shown so the
     digest can say "you're busy Saturday" instead of recommending into a clash.
  3. **Public crews** in the city — not events, but the answer to an empty weekend.

**What this deliberately is not: a scraper.** LifeOS does not know what is on at the city's
clubs, and Ticketmaster-style integrations are on the Don't-build list. An empty digest is an
honest report that nobody has published anything, and it says so and names the crews who
could — the atomic network in GROWTH.md is one crew that actually meets twice, and a digest
that invented events would hide exactly the signal that matters.

**Yours is never published and never leaves your slice.** The public half is read with
`find_public`, which forces `visibility == "public"`; the private half is read owner-scoped
and only ever rendered back to its owner. The shareable text is built from the digest the
caller already holds, so sharing it can only ever disclose what the caller could already see.
"""

import datetime

from modules.discover import core as discover_core
from modules.discover import discover
from modules.weekend import core
from substrate.graph import Graph

SCOPES = {"events:read", "content:read", "interests:read"}
MODULE = "weekend"

PRIVATE_TYPES = ("meet",)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _mine(session, window: dict, tz: int) -> list[dict]:
    """Your own weekend: confirmed meets and calendar blocks, owner-scoped.

    ICS rows may legitimately have no title — `store_titles` is off by default, because
    syncing a work calendar into a personal graph should not require handing over what the
    meetings are called. An untitled busy block still belongs in the digest; "Busy" is the
    honest rendering of it.
    """
    out = []
    for ev in session.find_entities("event", limit=400):
        a = ev["attrs"]
        if not core.in_window(a.get("start"), window, tz):
            continue
        if a.get("type") not in PRIVATE_TYPES and a.get("source") != "ics":
            continue
        out.append({"id": ev["id"], "kind": "yours", "title": a.get("title") or "Busy",
                    "start": a.get("start", ""), "place": a.get("place", ""),
                    "crew_id": a.get("crew_id", ""), "going_count": 0})
    return out


def _city_matches(item: dict, city: str) -> bool:
    if not city:
        return True
    return (item.get("city") or "").strip().lower() == city.strip().lower()


def weekend(graph: Graph, city: str = "", interests=None, offset: int = 0,
            now: str = "", tz_offset_minutes: int = 0, limit_per_day: int = 8) -> dict:
    """What's on this weekend, ranked, bucketed by day, with a shareable rendering."""
    session = graph.session(MODULE, SCOPES)
    now = now or _now()
    window = core.weekend_window(now, offset=offset, tz_offset_minutes=tz_offset_minutes)
    wants = list(interests) if interests else discover.profile_interests(graph)

    public = [e for e in discover._event_items(session)
              if e.get("visibility") == "public" and _city_matches(e, city)
              and core.in_window(e.get("start"), window, tz_offset_minutes)]
    # Ranked, but NOT filtered by score: `rank_feed` drops items that are neither
    # interest-matched nor popular, which is right for an infinite feed and wrong for a
    # finite weekend — "everything on, Friday to Sunday" has to mean everything.
    ranked = {r["id"]: r for r in discover_core.rank_feed(public, wants, now="", limit=500)}
    open_items = [{**e, **ranked.get(e["id"], {"score": 0.0, "reasons": []})} for e in public]
    open_items.sort(key=lambda i: (-(i.get("score") or 0), i.get("start") or ""))

    open_by_day = core.bucket(open_items, window, tz_offset_minutes)
    mine_by_day = core.bucket(_mine(session, window, tz_offset_minutes), window,
                              tz_offset_minutes)

    days = []
    for day in window["days"]:
        rows = open_by_day.get(day["date"], [])
        days.append({**day, "yours": mine_by_day.get(day["date"], []),
                     "open": rows[:max(0, limit_per_day)]})

    trimmed = False
    if window["is_underway"]:
        days, trimmed = core.drop_past(days, now, tz_offset_minutes)

    crews = [c for c in discover._crew_items(session)
             if c.get("visibility") == "public" and _city_matches(c, city)]

    digest = {
        "city": city, "interests": wants, "label": window["label"],
        "start": window["start"], "end": window["end"],
        "is_underway": window["is_underway"], "trimmed_to_whats_left": trimmed,
        "when_label": "rest of the weekend" if trimmed else _when_label(offset),
        "days": days, "crews": crews[:5],
        "counts": {"open": sum(len(d["open"]) for d in days),
                   "yours": sum(len(d["yours"]) for d in days),
                   "crews": len(crews)},
    }
    digest["text"] = core.render(digest)
    return digest


def _when_label(offset: int) -> str:
    if offset == 0:
        return "this weekend"
    if offset == 1:
        return "next weekend"
    if offset == -1:
        return "last weekend"
    return f"the weekend {abs(offset)} weeks {'ahead' if offset > 0 else 'ago'}"


def shareable(graph: Graph, city: str = "", offset: int = 0, include_yours: bool = False,
              **kwargs) -> dict:
    """The text to send a friend.

    `include_yours` is **off by default and that is the whole point**: your dentist
    appointment is in the digest so it can warn *you* about a clash, and there is no version
    of "here's what's on this weekend" that should carry it to someone else. Opting in is a
    deliberate act, not the path of least resistance.
    """
    digest = weekend(graph, city=city, offset=offset, **kwargs)
    if not include_yours:
        digest = {**digest, "days": [{**d, "yours": []} for d in digest["days"]]}
        digest["text"] = core.render(digest)
    return {"city": city, "label": digest["label"], "text": digest["text"],
            "counts": digest["counts"], "includes_your_own_plans": bool(include_yours)}
