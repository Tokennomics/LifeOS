"""Which cities stay fresh, and a new one filling the moment somebody names it.

The refresh loop covers what it can justify: configured cities, venue feeds, seeded places,
and now the two signals people give without being asked — "I'm in Lisbon" and "I'm going to
Porto next week". Neither leaks who: only the city name reaches the loop. A trip that has
ended stops counting, and so does an arrival that expired or was withdrawn.

A new city also gets its listings straight away rather than at the next pass, and the
operator card that advertised "Stream Event Feeds (284)" shows the real loop instead.
"""

import datetime
import pathlib

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import arrival
from modules.discover import discover
from modules.feeds import autosync, ingest
from modules.feeds.providers import ticketmaster
from substrate.graph import Graph

APP = (pathlib.Path(__file__).resolve().parent.parent / "surfaces/app/www/app.js").read_text()
PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.delenv(autosync.CITIES_VAR, raising=False)
    monkeypatch.delenv(ticketmaster.ENV_VAR, raising=False)
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


def _day(offset):
    return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()


def _covered(graph):
    return {c["city"]: c["why"] for c in autosync.cities(graph)}


def test_a_live_arrival_puts_its_city_on_the_list(graph):
    arrival.announce(graph, "Lisbon", account_id="acct-ana", handle="ana")
    assert _covered(graph)["lisbon"] == ["someone is there"]


def test_a_withdrawn_arrival_does_not(graph):
    arrival.announce(graph, "Lisbon", account_id="acct-ana", handle="ana")
    arrival.withdraw(graph, "Lisbon", account_id="acct-ana")
    assert "lisbon" not in _covered(graph)


def test_a_planned_trip_counts_until_it_ends(graph):
    discover.set_intent(graph, "Porto", ["fado"], starts=_day(3), ends=_day(6))
    discover.set_intent(graph, "Madrid", [], starts=_day(-9), ends=_day(-2))
    discover.set_intent(graph, "Seville", [])
    covered = _covered(graph)
    assert covered["porto"] == ["trip planned"] and "seville" in covered
    assert "madrid" not in covered


def test_another_accounts_trip_counts_too_but_only_its_city(graph):
    discover.set_intent(Graph(graph.conn, graph.bus, default_owner="acct-other"),
                        "Porto", ["secret interest"])
    entry = [c for c in autosync.cities(graph) if c["city"] == "porto"][0]
    assert entry == {"city": "porto", "label": "Porto", "why": ["trip planned"]}


def test_listings_for_one_city_are_fetched_now_when_keyed(graph, monkeypatch):
    monkeypatch.setenv(ticketmaster.ENV_VAR, "k")
    asked = []
    monkeypatch.setattr(ticketmaster, "search", lambda city="", size=50, **kw:
                        asked.append(city) or {"status": "ok", "items": []})
    out = autosync.refresh_listings(graph, "Porto")
    assert asked == ["Porto"] and out[0]["status"] == "ok"


def test_and_nothing_is_asked_without_a_key(graph, monkeypatch):
    called = []
    monkeypatch.setattr(ticketmaster, "search", lambda **kw: called.append(1))
    assert autosync.refresh_listings(graph, "Porto") == [] and called == []


def test_planning_a_trip_queues_the_destination(cfg, monkeypatch):
    queued = []
    from modules.city import autoseed
    monkeypatch.setattr(autoseed, "request", lambda g, city, **k: queued.append(city) or
                        {"queued": False})
    client = TestClient(create_app(cfg))
    res = client.post("/v1/discover/intents", json={"city": "Porto", "interests": ["fado"]})
    assert res.status_code == 200 and queued == ["Porto"]


def test_a_new_city_gets_listings_in_the_same_background_task(cfg, monkeypatch):
    from modules.city import autoseed
    monkeypatch.setattr(autoseed, "request", lambda g, city, **k: {"queued": True})
    monkeypatch.setattr(autoseed, "drain", lambda g, limit=1: {})
    fetched = []
    monkeypatch.setattr(autosync, "refresh_listings", lambda g, city: fetched.append(city))
    client = TestClient(create_app(cfg))
    client.post("/v1/discover/intents", json={"city": "Porto"})
    assert fetched == ["Porto"]


def test_the_operator_card_no_longer_invents_a_count():
    import re
    label = re.search(r'data-act="stream-auto-events">([^<]*)<', APP).group(1)
    assert not re.search(r"\d", label), label
    assert '"/v1/feeds/autosync"' in APP and '"/v1/feeds/autosync/run"' in APP
