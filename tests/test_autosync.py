"""Public listings refresh on their own — and say when they did.

Venue feeds, Ticketmaster and OpenStreetMap places all existed and all ran only when
somebody called an endpoint, so a deployed box showed whatever was true the last time an
operator remembered. These pin the loop: which cities it covers and why, that every
account's venue subscriptions are refreshed (not just the owner's), that a missing key is a
status rather than a write, that places are re-seeded weekly rather than every pass, and
that the loop is off unless configured — no test, laptop or second `create_app` starts a
thread.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import places
from modules.feeds import autosync, ingest
from modules.feeds.providers import ticketmaster
from substrate.graph import Graph

GEOCODE = {"results": [{"name": "Lisbon", "country": "Portugal",
                        "latitude": 38.72, "longitude": -9.13}]}
OVERPASS = {"elements": [{"type": "node", "id": 42, "lat": 38.71, "lon": -9.14,
                          "tags": {"name": "Café Real"}}]}


def _ics():
    when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    return ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nSUMMARY:Fado night\n"
            f"DTSTART:{when.strftime('%Y%m%dT%H%M%SZ')}\n"
            f"DTEND:{(when + datetime.timedelta(hours=3)).strftime('%Y%m%dT%H%M%SZ')}\n"
            "END:VEVENT\nEND:VCALENDAR\n")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.delenv(autosync.HOURS_VAR, raising=False)
    monkeypatch.delenv(autosync.CITIES_VAR, raising=False)
    monkeypatch.delenv(ticketmaster.ENV_VAR, raising=False)
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")
    monkeypatch.setattr(ingest, "_fetch", lambda url: _ics())


def _run(graph, overpass_calls=None):
    def overpass(url, query):
        if overpass_calls is not None:
            overpass_calls.append(query)
        return OVERPASS
    return autosync.run_once(graph, places_fetch=overpass,
                             geocode_fetch=lambda u, p: GEOCODE)


# ---- coverage --------------------------------------------------------------------

def test_no_cities_means_nothing_to_refresh_and_it_says_so(graph):
    s = autosync.status(graph)
    assert s["cities"] == [] and s["suggestion"]
    assert s["enabled"] is False and autosync.HOURS_VAR in s["why"]


def test_cities_come_from_config_feeds_and_seeded_places_with_reasons(graph, monkeypatch):
    monkeypatch.setenv(autosync.CITIES_VAR, "Berlin, Lisbon")
    ingest.add_feed(graph, "https://venue.example/e.ics", city="Lisbon")
    covered = {c["city"]: c["why"] for c in autosync.cities(graph)}
    assert set(covered) == {"berlin", "lisbon"}
    assert covered["lisbon"] == [autosync.CITIES_VAR, "venue feed"]


# ---- one pass --------------------------------------------------------------------

def test_a_pass_refreshes_every_accounts_venue_feeds(graph, cfg):
    """A subscription belongs to whoever added it. The loop has to see them all."""
    someone_else = Graph(graph.conn, graph.bus, default_owner="acct-other")
    ingest.add_feed(someone_else, "https://theirs.example/e.ics", city="Lisbon")
    ingest.add_feed(graph, "https://mine.example/e.ics", city="Lisbon")
    run = _run(graph)
    assert run["steps"]["venue_feeds"]["synced"] == 2
    assert run["steps"]["venue_feeds"]["added"] >= 1


def test_no_listings_key_is_a_status_not_a_write(graph, monkeypatch):
    monkeypatch.setenv(autosync.CITIES_VAR, "Lisbon")
    run = _run(graph)
    assert run["steps"]["listings"] == [{"provider": "ticketmaster",
                                         "status": "not_configured",
                                         "needs": ticketmaster.ENV_VAR}]


def test_with_a_key_each_city_is_asked_for_listings(graph, monkeypatch):
    monkeypatch.setenv(autosync.CITIES_VAR, "Lisbon, Porto")
    monkeypatch.setenv(ticketmaster.ENV_VAR, "k")
    asked = []
    monkeypatch.setattr(ticketmaster, "search",
                        lambda city="", size=50, **kw: asked.append(city) or
                        {"status": "ok", "items": []})
    run = _run(graph)
    assert sorted(asked) == ["Lisbon", "Porto"]
    assert {r["status"] for r in run["steps"]["listings"]} == {"ok"}


def test_places_are_seeded_then_left_alone_for_a_week(graph, monkeypatch):
    monkeypatch.setenv(autosync.CITIES_VAR, "Lisbon")
    calls = []
    first = _run(graph, calls)
    assert first["steps"]["places"][0]["status"] == "ok"
    assert places.listing(graph, "Lisbon")["total"] >= 1
    n = len(calls)
    second = _run(graph, calls)
    assert second["steps"]["places"][0]["status"] == "fresh"
    assert len(calls) == n, "a fresh city must not hit Overpass again"


def test_one_failing_step_does_not_stop_the_others(graph, monkeypatch):
    monkeypatch.setenv(autosync.CITIES_VAR, "Lisbon")
    monkeypatch.setattr(ingest, "sync_all", lambda *a, **k: 1 / 0)
    run = _run(graph)
    assert "ZeroDivisionError" in run["steps"]["venue_feeds"]["error"]
    assert run["steps"]["places"][0]["status"] == "ok"


def test_every_pass_is_recorded_and_shown(graph, monkeypatch):
    monkeypatch.setenv(autosync.HOURS_VAR, "6")
    monkeypatch.setenv(autosync.CITIES_VAR, "Lisbon")
    _run(graph)
    s = autosync.status(graph)
    assert s["enabled"] is True and s["last_run"]["steps"]["cities"] == ["lisbon"]
    assert s["next_due"] > s["last_run"]["finished_at"]


def test_old_runs_are_trimmed(graph, monkeypatch):
    monkeypatch.setattr(autosync, "KEEP_RUNS", 2)
    for _ in range(4):
        _run(graph)
    assert len(autosync.runs(graph, limit=10)) == 2


# ---- the thread ------------------------------------------------------------------

def test_the_loop_does_not_start_unless_configured(graph, monkeypatch):
    started = []
    monkeypatch.setattr(autosync.threading, "Thread",
                        lambda **kw: started.append(kw) or type("T", (), {"start": lambda s: None})())
    monkeypatch.setattr(autosync, "_STARTED", False)
    assert autosync.start(graph) is False and started == []
    monkeypatch.setenv(autosync.HOURS_VAR, "6")
    assert autosync.start(graph) is True and len(started) == 1
    assert autosync.start(graph) is False and len(started) == 1, "once per process"


def test_create_app_starts_nothing_by_default(cfg, monkeypatch):
    monkeypatch.setattr(autosync, "_STARTED", False)
    create_app(cfg)
    assert autosync._STARTED is False


def test_the_routes(cfg, monkeypatch):
    monkeypatch.setattr(autosync, "_STARTED", False)
    monkeypatch.setattr(places, "seed", lambda *a, **k: {"status": "ok", "added": 0,
                                                                  "updated": 0},
                        raising=False)
    client = TestClient(create_app(cfg))
    assert client.get("/v1/feeds/autosync").json()["enabled"] is False
    ran = client.post("/v1/feeds/autosync/run").json()
    assert "venue_feeds" in ran["steps"]
    assert client.get("/v1/feeds/autosync").json()["recent"][0]["started_at"] == ran["started_at"]


# ---- events without DTEND ------------------------------------------------------

@pytest.mark.parametrize("body,end", [
    ("DTSTART:20261010T200000Z", "2026-10-10T20:00:00+00:00"),
    ("DTSTART:20261010T200000Z\nDURATION:PT2H30M", "2026-10-10T22:30:00+00:00"),
    ("DTSTART;VALUE=DATE:20261010", "2026-10-11T00:00:00+00:00"),
    ("DTSTART:20261010T200000Z\nDTEND:20261010T230000Z", "2026-10-10T23:00:00+00:00"),
])
def test_an_event_without_dtend_is_kept(body, end):
    """RFC 5545 makes DTEND optional. The parser required it, so every public calendar that
    omits it contributed nothing to the refresh — found while writing this file, when an
    ICS with only DTSTART synced 'ok' and added zero events."""
    from modules.feeds import parse
    ics = f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nSUMMARY:X\n{body}\nEND:VEVENT\nEND:VCALENDAR\n"
    items = parse.parse_feed(ics)
    assert [i["end"] for i in items] == [end]


def test_a_zero_length_event_blocks_no_busy_time():
    from modules.calendars import freebusy
    ics = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nDTSTART:20261010T200000Z\nEND:VEVENT\nEND:VCALENDAR\n"
    ev = freebusy.parse_ics(ics)[0]
    assert ev["start"] == ev["end"]


def test_the_vps_loop_also_refreshes_other_accounts_feeds(graph):
    """tools/feedsync read through the config owner's slice, so a venue another account
    subscribed to was never refreshed on the VPS either."""
    from tools import feedsync
    ingest.add_feed(Graph(graph.conn, graph.bus, default_owner="acct-other"),
                    "https://theirs.example/e.ics", city="Lisbon")
    assert feedsync.run_once(graph, min_interval_minutes=0)["feeds"] == 1
