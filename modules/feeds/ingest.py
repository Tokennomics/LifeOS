"""Venue feeds — graph flow: subscribe to an ICS/RSS feed, sync it into public events.

The cheapest real answer to an empty directory. Venues, clubs and collectives already
publish calendars; this reads them. No API key, no scraping, no terms-of-service exposure —
a feed is published *to be* read, which is the whole difference between this and the tiers
parked in ROADMAP under "Event aggregation".

Two ownership decisions, and they are not arbitrary:

- **The subscription is yours; the events are everyone's.** The `venue_feed` record is
  owner-scoped, because adding a feed is a thing *you* did. The events it produces are
  written to the SYSTEM owner with `visibility: "public"`, because a listing for a public
  club night is not anybody's private data and every account should see it once.
- **Dedupe is global, keyed on `(feed url, item uid)`.** Two people subscribing to the same
  venue must not double every event in the city. Because the key does not include who
  subscribed, the second subscription is a no-op on content and the first one's rows simply
  get refreshed.

**Listings are labelled as listings.** Every ingested event carries `origin: "feed"` and its
`venue`, and the weekend digest renders those with a `· listed` marker. A scraped club night
and "six people from your climbing crew agreed on Thursday" are different products in the
same list, and a directory that blurs them buys density by spending the only signal worth
having — GROWTH.md's atomic network is one crew that actually *meets*, and that has to stay
legible next to a wall of listings.

Sync is idempotent, bounded (`MAX_ITEMS` per feed), and never raises on a bad feed: a venue
that serves an error page gets recorded as a failure on its own record and the other feeds
carry on.
"""

import datetime

from modules.feeds import discover, parse
from substrate import SYSTEM_OWNER, now_iso, safefetch
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "events:read", "events:write"}
MODULE = "feeds"

FEED = "venue_feed"
ORIGIN = "feed"
MAX_ITEMS = 200
STALE_DAYS = 30          # listings that finished before this are not worth carrying
HORIZON_DAYS = 120


def _sys(graph: Graph):
    """Ingested listings are system-owned so one city's events exist once, not per-account."""
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _norm(value, cap: int = 120) -> str:
    return str(value or "").strip()[:cap]


def add_feed(graph: Graph, url: str, city: str = "", venue: str = "", topic: str = "",
             source: str = MODULE) -> dict:
    """Subscribe to a venue's calendar. Nothing is fetched here — `sync` does that, so
    adding a feed can never block on a slow server."""
    url = _norm(url, 500)
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("a feed needs an http(s) url")
    session = graph.session(MODULE, SCOPES)
    existing = session.find_entities("content", {"type": FEED, "url": url}, limit=1)
    if existing:
        return {"feed_id": existing[0]["id"], "url": url, "added": False}
    feed_id = session.create_entity("content", {
        "type": FEED, "url": url, "city": _norm(city, 60), "venue": _norm(venue, 80),
        "topic": _norm(topic, 40), "added_at": now_iso(), "last_status": "never synced",
    }, source=source)
    return {"feed_id": feed_id, "url": url, "city": _norm(city, 60),
            "venue": _norm(venue, 80), "added": True}


def feeds(graph: Graph, limit: int = 100) -> list[dict]:
    session = graph.session(MODULE, SCOPES)
    out = []
    for row in session.find_entities("content", {"type": FEED}, limit=limit):
        a = row["attrs"]
        out.append({"id": row["id"], "url": a.get("url", ""), "city": a.get("city", ""),
                    "venue": a.get("venue", ""), "topic": a.get("topic", ""),
                    "last_status": a.get("last_status", ""),
                    "last_synced_at": a.get("last_synced_at", ""),
                    "last_count": a.get("last_count", 0)})
    return out


def remove_feed(graph: Graph, feed_id: str, source: str = MODULE) -> dict:
    """Stop following a venue. Events already ingested stay — they are public listings that
    other accounts may be looking at, and unsubscribing is not a retraction."""
    session = graph.session(MODULE, SCOPES)
    row = session.get_entity(feed_id)
    if row is None or row["attrs"].get("type") != FEED:
        raise ValueError("unknown feed")
    session.update_entity(feed_id, {"removed": True, "removed_at": now_iso()}, source=source)
    return {"feed_id": feed_id, "removed": True}


def _fetch(url: str) -> str:
    """Every URL here was chosen by a user, so it goes through the SSRF guard. See
    substrate/safefetch.py — the danger is not the venue, it is the cloud metadata service
    sitting unauthenticated on a link-local address inside every hosted box."""
    return safefetch.fetch_text(url)


def _dedupe_key(url: str, uid: str) -> str:
    return f"{url}#{uid}"


def _in_horizon(start: str, now: datetime.datetime) -> bool:
    """Ignore last year's archive and speculative dates a decade out. A venue feed that
    contains its whole history would otherwise import the whole history."""
    when = parse_start(start)
    if when is None:
        return False
    return (now - datetime.timedelta(days=STALE_DAYS) <= when
            <= now + datetime.timedelta(days=HORIZON_DAYS))


def parse_start(value: str):
    try:
        when = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:
            return datetime.datetime.combine(
                datetime.date.fromisoformat(str(value)[:10]), datetime.time.min)
        except (ValueError, TypeError):
            return None
    return when.astimezone(datetime.timezone.utc).replace(tzinfo=None) \
        if when.tzinfo else when


def sync(graph: Graph, feed_id: str, text: str = "", now: str = "",
         source: str = MODULE) -> dict:
    """Pull one feed in. `text` bypasses the fetch, which is what tests and offline
    imports use — no feature here requires the network to be reachable to be testable."""
    session = graph.session(MODULE, SCOPES)
    feed = session.get_entity(feed_id)
    if feed is None or feed["attrs"].get("type") != FEED:
        raise ValueError("unknown feed")
    a = feed["attrs"]
    url = a.get("url", "")

    if not text:
        try:
            text = _fetch(url)
        except Exception as exc:                     # a dead venue must not kill the sync
            session.update_entity(feed_id, {
                "last_status": f"fetch failed: {type(exc).__name__}",
                "last_synced_at": now_iso()}, source=source)
            return {"feed_id": feed_id, "status": "fetch_failed", "added": 0, "updated": 0,
                    "skipped_no_date": 0, "skipped_out_of_range": 0}

    stamp = parse_start(now) if now else datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    items = parse.parse_feed(text)[:MAX_ITEMS]
    system = _sys(graph)

    added = updated = no_date = out_of_range = 0
    for item in items:
        if item.get("skipped") == "no_date" or not item.get("start"):
            no_date += 1
            continue
        if not _in_horizon(item["start"], stamp):
            out_of_range += 1
            continue

        key = _dedupe_key(url, item.get("uid") or item.get("title", ""))
        attrs = {
            "type": "social", "title": item.get("title") or a.get("venue") or "Event",
            "start": item["start"], "end": item.get("end", ""),
            "place": item.get("place") or a.get("venue", ""),
            "city": a.get("city", ""), "topic": a.get("topic", ""),
            "visibility": "public", "busy": False,
            "origin": ORIGIN, "feed_key": key, "feed_url": url,
            "venue": a.get("venue", ""), "url": item.get("url", ""),
        }
        existing = system.find_entities("event", {"feed_key": key}, limit=1)
        if existing:
            system.update_entity(existing[0]["id"], attrs, source=source)
            updated += 1
        else:
            system.create_entity("event", {**attrs, "created_at": now_iso()},
                                 source=source, owner_id=SYSTEM_OWNER)
            added += 1

    status = f"ok: {added} added, {updated} updated"
    session.update_entity(feed_id, {
        "last_status": status, "last_synced_at": now_iso(),
        "last_count": added + updated}, source=source)
    return {"feed_id": feed_id, "status": "ok", "added": added, "updated": updated,
            "skipped_no_date": no_date, "skipped_out_of_range": out_of_range}


def discover_feeds(graph: Graph, url: str, html: str = "", add: bool = False,
                   city: str = "", venue: str = "", topic: str = "",
                   source: str = MODULE) -> dict:
    """Given a venue's website, propose its calendar feeds. Nothing is added by default.

    `add=True` subscribes to the top candidate, which is a convenience for the obvious case
    and never the default: a page can advertise a dozen feeds and only the human knows which
    one is the gig calendar rather than the blog. `html` bypasses the fetch, same door the
    rest of this module offers.
    """
    url = _norm(url, 500)
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("a venue needs an http(s) url")

    # Already a feed? Then there is nothing to discover and pretending otherwise wastes a
    # round trip and the user's patience.
    if not html and discover.looks_like_feed_url(url):
        candidates = [{"url": url, "kind": "ics" if url.lower().endswith((".ics", ".ical"))
                       else "rss", "title": "", "advertised": False, "score": 5.0}]
    else:
        if not html:
            try:
                html = _fetch(url)
            except Exception as exc:
                return {"url": url, "status": f"fetch failed: {type(exc).__name__}",
                        "candidates": [], "added": None}
        candidates = discover.find_feeds(html, base_url=url)

    added = None
    if add and candidates:
        added = add_feed(graph, candidates[0]["url"], city=city,
                         venue=venue or _host(url), topic=topic, source=source)
    return {"url": url, "status": "ok", "candidates": candidates, "added": added}


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc.removeprefix("www.")[:80]


# ---- Tier 2: official APIs ---------------------------------------------------

def sync_provider(graph: Graph, name: str, city: str = "", size: int = 50,
                  now: str = "", source: str = MODULE, **kwargs) -> dict:
    """Pull a city from an official API into the same public events as a venue feed.

    Deliberately shares every rule with `sync`: system-owned public rows, `origin: "feed"`
    so it renders as `· listed`, a global dedupe key, and the same horizon. A provider is a
    different way to *find* listings, not a different kind of thing to store — which is why
    the weekend digest needed no changes at all to show them.

    An unconfigured provider returns `not_configured` and writes nothing. That is the
    ROADMAP condition on this tier: no key degrades to the feed-and-crew list, never errors.
    """
    from modules.feeds import providers

    provider = providers.get(name)
    # A weather or places provider has a different search signature and produces something
    # that is not an event. Registering them in one registry is right — they are all
    # "outside data" — but handing one to the event sync would be a confusing TypeError
    # rather than a clear no.
    if getattr(provider, "KIND", "events") != "events":
        raise ValueError(
            f"{provider.NAME} provides {provider.KIND}, not events — "
            f"it cannot be synced into the event feed")
    result = provider.search(city=city, size=size, **kwargs)
    if result["status"] != "ok":
        return {"provider": provider.NAME, "city": city, "status": result["status"],
                "added": 0, "updated": 0, "skipped_out_of_range": 0,
                "detail": result.get("detail", "")}

    stamp = parse_start(now) if now else datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    system = _sys(graph)
    added = updated = out_of_range = 0

    for item in result["items"][:MAX_ITEMS]:
        if not _in_horizon(item["start"], stamp):
            out_of_range += 1
            continue
        key = _dedupe_key(f"provider:{provider.NAME}", item["uid"])
        attrs = {
            "type": "social", "title": item.get("title") or "Event",
            "start": item["start"], "end": item.get("end", ""),
            "place": item.get("place", ""), "city": item.get("city") or city,
            "topic": "", "visibility": "public", "busy": False,
            "origin": ORIGIN, "provider": provider.NAME, "feed_key": key,
            "feed_url": "", "venue": item.get("place", ""), "url": item.get("url", ""),
        }
        existing = system.find_entities("event", {"feed_key": key}, limit=1)
        if existing:
            system.update_entity(existing[0]["id"], attrs, source=source)
            updated += 1
        else:
            system.create_entity("event", {**attrs, "created_at": now_iso()},
                                 source=source, owner_id=SYSTEM_OWNER)
            added += 1

    return {"provider": provider.NAME, "city": city, "status": "ok", "added": added,
            "updated": updated, "skipped_out_of_range": out_of_range}


def _synced_within(feed: dict, minutes: int, now: datetime.datetime) -> bool:
    last = parse_start(feed.get("last_synced_at", ""))
    if last is None:
        return False
    return (now - last) < datetime.timedelta(minutes=max(0, minutes))


def sync_all(graph: Graph, source: str = MODULE, min_interval_minutes: int = 0,
             now: str = "") -> dict:
    """Sync every live subscription. One bad feed is reported, not fatal.

    `min_interval_minutes` is what makes this safe to run on a loop. Without it a scheduler
    that fires every ten minutes hits every venue every ten minutes forever — a small
    venue's server does not deserve that, and a well-behaved reader is the price of the
    "a feed is published to be read" argument this whole module rests on. Skipped feeds are
    reported as skipped rather than silently dropped, so a scheduler that is doing nothing
    looks different from one that is not running.
    """
    stamp = parse_start(now) if now else datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    results, skipped = [], []
    for feed in feeds(graph):
        row = graph.session(MODULE, SCOPES).get_entity(feed["id"])
        if row and row["attrs"].get("removed"):
            continue
        if min_interval_minutes and _synced_within(feed, min_interval_minutes, stamp):
            skipped.append(feed["url"])
            continue
        results.append({**sync(graph, feed["id"], source=source), "url": feed["url"]})
    return {"feeds": len(results), "results": results, "skipped_recent": skipped,
            "added": sum(r["added"] for r in results),
            "updated": sum(r["updated"] for r in results)}
