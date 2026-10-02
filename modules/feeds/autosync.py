"""Keep public listings fresh without anybody pressing a button.

Everything that sources public data already existed — venue ICS/RSS feeds (`ingest`),
Ticketmaster's Discovery API (`providers.ticketmaster`), OpenStreetMap places
(`city.places`) — and every one of them ran only when somebody called an endpoint. A
deployed box therefore showed whatever was true the last time an operator remembered, and
a city nobody had touched for a fortnight showed last fortnight's weekend.

This is the loop that was missing. One pass:

1. **Venue feeds** — `ingest.sync_all` with `min_interval_minutes`, so a small venue's
   server is read once per interval however often the loop wakes.
2. **Listings APIs** — each configured events provider, for each covered city. With no
   key this step reports `not_configured` and writes nothing, as the provider rule says.
3. **Places** — OpenStreetMap, re-seeded per covered city when the last refresh is older
   than `PLACES_EVERY_DAYS`. Overpass is a volunteer service; weekly is plenty for cafés.

Which cities are "covered" is derived, never invented: the ones named in
`LIFEOS_SYNC_CITIES`, the ones somebody subscribed a venue feed for, and the ones whose
places were already seeded. An instance with none of those has nothing to refresh, and
says so.

Every pass writes one `autosync_run` row (system-owned) with what each step did, so
`status()` can say when it last ran and what happened — a scheduler that is silently not
running must look different from one that ran and found nothing.

`tools/feedsync.py` already refreshed venue feeds, as its own container in the VPS compose
file. Render has no such option: the database is one SQLite file on a disk only the web
service can mount, so a Render cron job cannot reach it. Hence a thread, and while it was
being added it took on the other two sources as well.

The loop is a daemon thread started by the gateway only when `LIFEOS_AUTOSYNC_HOURS` is a
positive number. It is off by default, so tests, a laptop, and `create_app` called fifty
times in a test run never start a thread or touch the network. render.yaml turns it on.
The deploy is one process with one SQLite file (no workers), so one thread is one
scheduler; `_STARTED` guards against a second `create_app` in the same process.
"""

import datetime
import os
import threading
import time

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "feeds.autosync"
SCOPES = {"content:read", "content:write", "events:read", "events:write"}
RUN_RECORD = "autosync_run"

HOURS_VAR = "LIFEOS_AUTOSYNC_HOURS"
CITIES_VAR = "LIFEOS_SYNC_CITIES"
PLACES_EVERY_DAYS = 7
MAX_CITIES = 25
KEEP_RUNS = 50
FIRST_RUN_DELAY_S = 60      # let the box pass its health check before reaching out

_STARTED = False
_LOCK = threading.Lock()


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp) -> datetime.datetime | None:
    try:
        value = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)


def interval_hours() -> float:
    try:
        return max(0.0, float(str(os.environ.get(HOURS_VAR, "")).strip() or 0))
    except ValueError:
        return 0.0


def _configured_cities() -> list[str]:
    raw = str(os.environ.get(CITIES_VAR, ""))
    return [c.strip() for c in raw.split(",") if c.strip()]


def cities(graph: Graph) -> list[dict]:
    """Every city this instance keeps fresh, and why each one is on the list."""
    from modules.city import chat
    from modules.feeds import ingest

    found: dict[str, dict] = {}

    def add(label: str, why: str):
        label = str(label or "").strip()
        if not label:
            return
        slug = chat.slug(label)
        if not slug:
            return
        entry = found.setdefault(slug, {"city": slug, "label": label, "why": []})
        if why not in entry["why"]:
            entry["why"].append(why)

    for name in _configured_cities():
        add(name, CITIES_VAR)
    for feed in ingest.feeds(_graph_all(graph), limit=500):
        add(feed.get("city", ""), "venue feed")
    for row in _sys(graph).find_entities("content", {"type": "city_place"}, limit=5000):
        add(row["attrs"].get("city_label") or row["attrs"].get("city", ""), "places seeded")
    return list(found.values())[:MAX_CITIES]


def _graph_all(graph: Graph) -> Graph:
    """Every owner's slice at once. A venue subscription belongs to whoever added it, but
    the events it produces are public and system-owned, so the refresh has to see every
    subscription on the box. Nothing is created through this handle — `sync` writes events
    under SYSTEM_OWNER explicitly and only updates the feed row it was given."""
    return Graph(graph.conn, graph.bus, default_owner=None)


def _places_age_days(graph: Graph, city_slug: str) -> float | None:
    rows = _sys(graph).find_entities("content", {"type": "city_place", "city": city_slug},
                                     limit=2000)
    stamps = [_parse(r["attrs"].get("refreshed_at")) for r in rows]
    stamps = [s for s in stamps if s]
    if not stamps:
        return None
    return (_now() - max(stamps)).total_seconds() / 86400


def run_once(graph: Graph, *, places_fetch=None, geocode_fetch=None,
             source: str = MODULE) -> dict:
    """One full pass. Never raises — each step's failure is recorded and the next runs."""
    from modules.city import places
    from modules.feeds import ingest, providers

    started = now_iso()
    hours = interval_hours() or 6.0
    covered = cities(graph)
    steps: dict = {"cities": [c["city"] for c in covered]}

    try:
        feeds_result = ingest.sync_all(_graph_all(graph), source=source,
                                       min_interval_minutes=int(hours * 60) - 5)
        steps["venue_feeds"] = {"synced": feeds_result["feeds"],
                                "skipped_recent": len(feeds_result["skipped_recent"]),
                                "added": feeds_result["added"],
                                "updated": feeds_result["updated"],
                                "failed": [r["url"] for r in feeds_result["results"]
                                           if r.get("status") not in (None, "ok")]}
    except Exception as exc:
        steps["venue_feeds"] = {"error": f"{type(exc).__name__}: {exc}"}

    listings = []
    for prov in providers.status():
        if prov["kind"] != "events":
            continue
        if not prov["configured"]:
            listings.append({"provider": prov["name"], "status": "not_configured",
                             "needs": prov["env_var"]})
            continue
        for city in covered:
            try:
                r = ingest.sync_provider(graph, prov["name"], city=city["label"],
                                         source=source)
            except Exception as exc:
                r = {"provider": prov["name"], "city": city["city"],
                     "status": f"error: {type(exc).__name__}"}
            listings.append({k: r.get(k) for k in ("provider", "city", "status", "added",
                                                    "updated")})
    steps["listings"] = listings

    place_runs = []
    for city in covered:
        age = _places_age_days(graph, city["city"])
        if age is not None and age < PLACES_EVERY_DAYS:
            place_runs.append({"city": city["city"], "status": "fresh",
                               "age_days": round(age, 1)})
            continue
        try:
            r = places.seed(graph, city["label"], overpass_fetch=places_fetch,
                            geocode_fetch=geocode_fetch, source=source)
            place_runs.append({"city": city["city"], "status": r["status"],
                               "added": r["added"], "updated": r["updated"]})
        except Exception as exc:
            place_runs.append({"city": city["city"],
                               "status": f"error: {type(exc).__name__}"})
    steps["places"] = place_runs

    record = {"type": RUN_RECORD, "started_at": started, "finished_at": now_iso(),
              "steps": steps}
    session = _sys(graph)
    session.create_entity("content", record, source=source, owner_id=SYSTEM_OWNER)
    _trim(session, source)
    return record


def _trim(session, source: str):
    rows = session.find_entities("content", {"type": RUN_RECORD}, limit=KEEP_RUNS * 4)
    rows.sort(key=lambda r: r["attrs"].get("started_at", ""), reverse=True)
    for row in rows[KEEP_RUNS:]:
        session.delete_entity(row["id"], source=source)


def runs(graph: Graph, limit: int = 10) -> list[dict]:
    rows = _sys(graph).find_entities("content", {"type": RUN_RECORD}, limit=KEEP_RUNS * 4)
    rows.sort(key=lambda r: r["attrs"].get("started_at", ""), reverse=True)
    return [{k: r["attrs"].get(k) for k in ("started_at", "finished_at", "steps")}
            for r in rows[:limit]]


def status(graph: Graph) -> dict:
    """Is the loop on, when did it last run, what did it do, what is it covering."""
    hours = interval_hours()
    recent = runs(graph, limit=1)
    last = recent[0] if recent else None
    next_due = ""
    if hours and last:
        finished = _parse(last["finished_at"])
        if finished:
            next_due = (finished + datetime.timedelta(hours=hours)).isoformat()
    covered = cities(graph)
    return {
        "enabled": bool(hours),
        "running": _STARTED,
        "interval_hours": hours,
        "last_run": last,
        "next_due": next_due,
        "cities": covered,
        "why": "" if hours else (f"{HOURS_VAR} is not set, so nothing refreshes on its own. "
                                 "Set it (render.yaml uses 6) or run a pass by hand."),
        "suggestion": "" if covered else (
            f"No city is covered yet. Name some in {CITIES_VAR}, subscribe a venue feed, "
            "or seed a city's places."),
    }


def _due(graph: Graph, hours: float) -> float:
    """Seconds until the next pass is due (0 if overdue)."""
    recent = runs(graph, limit=1)
    if not recent:
        return 0.0
    finished = _parse(recent[0]["finished_at"])
    if not finished:
        return 0.0
    wait = (finished + datetime.timedelta(hours=hours) - _now()).total_seconds()
    return max(0.0, wait)


def _loop(graph: Graph, hours: float):
    time.sleep(FIRST_RUN_DELAY_S)
    while True:
        try:
            wait = _due(graph, hours)
            if wait > 0:
                time.sleep(min(wait, 3600))
                continue
            with _LOCK:
                result = run_once(graph)
            print(f"[autosync] pass done: {len(result['steps']['cities'])} cities")
        except Exception as exc:                 # never let the thread die
            print(f"[autosync] pass failed: {type(exc).__name__}: {exc}")
            time.sleep(600)


def start(graph: Graph) -> bool:
    """Start the loop once per process, only when configured. Returns whether it started."""
    global _STARTED
    hours = interval_hours()
    if not hours or _STARTED:
        return False
    _STARTED = True
    threading.Thread(target=_loop, args=(graph, hours), name="lifeos-autosync",
                     daemon=True).start()
    print(f"[autosync] on: every {hours:g}h")
    return True
