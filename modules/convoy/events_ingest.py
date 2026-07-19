"""Convoy — social event intake. P0: manual add (Ticketmaster ingest lands when an API key exists)."""

import datetime

from substrate.graph import Graph

SCOPES = {"events:read", "events:write", "people:read", "people:write"}


def add_social_event(graph: Graph, title: str, start_iso: str, place: str = "",
                     url: str = "", source: str = "convoy") -> str:
    datetime.datetime.fromisoformat(start_iso)  # validate
    session = graph.session("convoy", SCOPES)
    return session.create_entity(
        "event",
        {"type": "social", "status": "proposed", "title": title, "start": start_iso,
         "place": place, "url": url, "invited": [], "yes": [], "no": []},
        source=source,
    )


def upcoming(graph: Graph, include_past_hours: int = 6) -> list[dict]:
    session = graph.session("convoy", SCOPES)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=include_past_hours)
    events = []
    for ev in session.find_entities("event", {"type": "social"}, limit=100):
        if ev["attrs"].get("status") == "attended":
            continue
        try:
            start = datetime.datetime.fromisoformat(ev["attrs"].get("start", ""))
        except ValueError:
            continue
        if start.tzinfo is None:  # datetime-local inputs arrive naive — treat as UTC
            start = start.replace(tzinfo=datetime.timezone.utc)
        if start >= cutoff:
            events.append(ev)
    events.sort(key=lambda e: e["attrs"]["start"])
    return events
