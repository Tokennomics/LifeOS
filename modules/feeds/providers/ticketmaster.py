"""Ticketmaster Discovery API — the first Tier 2 provider.

Chosen over Eventbrite and Meetup for a practical reason: it still has an open, keyed REST
search endpoint that a solo developer can get a key for in a browser. Eventbrite removed
public event search from its API for third parties, and Meetup moved to an OAuth GraphQL
API — both are more integration work for coverage this codebase cannot yet use.

**Its coverage is ticketed and mainstream, and that is a known limitation rather than a
disappointment.** It will find the arena show and miss the basement party, which is exactly
the gap ROADMAP says Tier 3 would eventually fill. It is worth having anyway: a city with
the big listings in it is a city with *something* in it, and the seeded venue feeds are
where the interesting half comes from.

**Not verified against the live API.** The response shape below is coded from the documented
`_embedded.events[]` structure and exercised against recorded-shape fixtures; nothing in this
sandbox can reach api.ticketmaster.com. Treat the first real call as the test — the failure
mode is an empty result and a recorded status, not a crash, which is the point of the
defensive parsing here.
"""

import os

NAME = "ticketmaster"
ENV_VAR = "LIFEOS_TICKETMASTER_KEY"
BASE = "https://app.ticketmaster.com/discovery/v2/events.json"
MAX_SIZE = 100


def configured() -> bool:
    return bool(str(os.environ.get(ENV_VAR, "")).strip())


def _text(value, cap: int) -> str:
    return str(value or "").strip()[:cap]


def _venue_of(event: dict) -> tuple[str, str]:
    """(place, city) — every level of this is optional in real responses."""
    venues = ((event.get("_embedded") or {}).get("venues") or [])
    if not venues:
        return "", ""
    venue = venues[0] or {}
    return (_text(venue.get("name"), 80),
            _text((venue.get("city") or {}).get("name"), 60))


def _start_of(event: dict) -> str:
    dates = (event.get("dates") or {}).get("start") or {}
    # dateTime is the real instant; localDate is the fallback for a date-only listing.
    return _text(dates.get("dateTime") or dates.get("localDate"), 40)


def normalise(payload: dict) -> list[dict]:
    """API response -> the same item shape `parse.parse_feed` produces.

    Written to survive a response that is not what the docs say: every lookup tolerates a
    missing or wrongly-typed level, and an event with no id or no start is skipped rather
    than guessed at. An aggregator that invents a date is the thing this whole module
    refuses to be.
    """
    events = ((payload or {}).get("_embedded") or {}).get("events") or []
    if not isinstance(events, list):
        return []

    out = []
    for event in events:
        if not isinstance(event, dict):
            continue
        uid, start = _text(event.get("id"), 120), _start_of(event)
        if not uid or not start:
            continue
        place, city = _venue_of(event)
        out.append({"uid": uid, "title": _text(event.get("name"), 120), "start": start,
                    "end": "", "place": place, "city": city,
                    "url": _text(event.get("url"), 300), "format": NAME})
    return out


def search(city: str = "", size: int = 50, page: int = 0, fetch=None) -> dict:
    """Look a city up. Never raises: an unconfigured or unreachable provider is a status.

    `fetch` is injectable so the network is not a precondition for testing this — the same
    door `ingest.sync(text=...)` opens for feeds.
    """
    if not configured():
        return {"status": "not_configured", "items": [],
                "detail": f"{ENV_VAR} is not set; Tier 2 contributes nothing"}

    params = {"apikey": os.environ[ENV_VAR].strip(), "size": min(max(1, int(size)), MAX_SIZE),
              "page": max(0, int(page)), "sort": "date,asc"}
    if city:
        params["city"] = str(city)

    try:
        payload = (fetch or _fetch)(BASE, params)
    except Exception as exc:
        return {"status": f"fetch failed: {type(exc).__name__}", "items": []}
    return {"status": "ok", "items": normalise(payload)}


def _fetch(url: str, params: dict) -> dict:
    from substrate import safefetch
    return safefetch.fetch_json(url, params)
