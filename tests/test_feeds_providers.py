"""Tier 2 — official APIs, and the rule that governs them.

`Every feature works with no API key and improves with one` is the oldest rule in this repo,
and Tier 2 is the first thing that tests it. **No key must degrade to the feed-and-crew
list, never error.** Most of this file is that one sentence, checked from several directions.

The Ticketmaster response shape here is coded from the documented `_embedded.events[]`
structure. **Nothing in the sandbox can reach api.ticketmaster.com**, so these are
recorded-shape fixtures, not proof the live API matches — which is exactly why `normalise`
is written to survive a payload that is not what the docs say.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.feeds import ingest, providers
from modules.feeds.providers import ticketmaster
from substrate import SYSTEM_OWNER
from substrate.graph import Graph

KEY = "tm-test-key"
TUE = "2026-08-04T09:00:00+00:00"

PAYLOAD = {"_embedded": {"events": [
    {"id": "tm-1", "name": "Nina Kraviz", "url": "https://tm.example/tm-1",
     "dates": {"start": {"dateTime": "2026-08-07T22:00:00Z", "localDate": "2026-08-07"}},
     "_embedded": {"venues": [{"name": "Lux Frágil", "city": {"name": "Lisbon"}}]}},
    {"id": "tm-2", "name": "Date-only listing",
     "dates": {"start": {"localDate": "2026-08-08"}},
     "_embedded": {"venues": [{"name": "Coliseu"}]}},
]}}


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv(ticketmaster.ENV_VAR, KEY)


@pytest.fixture
def unkeyed(monkeypatch):
    monkeypatch.delenv(ticketmaster.ENV_VAR, raising=False)


def _fetch(url, params):
    assert params["apikey"] == KEY, "the key must actually be sent"
    return PAYLOAD


def _payload_relative(url=None, params=None):
    """PAYLOAD with its two listings moved to tomorrow and the day after."""
    if params is not None:
        assert params["apikey"] == KEY, "the key must actually be sent"
    now = datetime.datetime.now(datetime.timezone.utc)
    first, second = now + datetime.timedelta(days=1), now + datetime.timedelta(days=2)
    return {"_embedded": {"events": [
        {"id": "tm-1", "name": "Nina Kraviz", "url": "https://tm.example/tm-1",
         "dates": {"start": {"dateTime": first.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "localDate": first.strftime("%Y-%m-%d")}},
         "_embedded": {"venues": [{"name": "Lux Frágil", "city": {"name": "Lisbon"}}]}},
        {"id": "tm-2", "name": "Date-only listing",
         "dates": {"start": {"localDate": second.strftime("%Y-%m-%d")}},
         "_embedded": {"venues": [{"name": "Coliseu"}]}},
    ]}}


# ---- the rule ----------------------------------------------------------------

def test_no_key_is_a_status_not_an_error(unkeyed):
    result = ticketmaster.search(city="Lisbon")
    assert result["status"] == "not_configured" and result["items"] == []
    assert ticketmaster.ENV_VAR in result["detail"]


def test_no_key_writes_nothing_and_does_not_raise(graph, unkeyed):
    result = ingest.sync_provider(graph, "ticketmaster", city="Lisbon", now=TUE)
    assert result["status"] == "not_configured" and result["added"] == 0


def test_the_weekend_still_works_without_a_key(graph, unkeyed):
    """Degrading means the rest of the product is unaffected, not that it limps."""
    from modules.discover import discover
    from modules.weekend import digest
    discover.publish_event(graph, "Sushi night", start="2026-08-08T20:00:00+00:00",
                           city="Lisbon", visibility="public")
    ingest.sync_provider(graph, "ticketmaster", city="Lisbon", now=TUE)
    assert "Sushi night" in digest.weekend(graph, city="Lisbon", now=TUE)["text"]


def test_configured_reports_the_truth(monkeypatch):
    monkeypatch.setenv(ticketmaster.ENV_VAR, KEY)
    assert ticketmaster.configured() is True
    monkeypatch.setenv(ticketmaster.ENV_VAR, "   ")
    assert ticketmaster.configured() is False
    monkeypatch.delenv(ticketmaster.ENV_VAR, raising=False)
    assert ticketmaster.configured() is False


def test_the_provider_listing_never_returns_a_key(monkeypatch):
    monkeypatch.setenv(ticketmaster.ENV_VAR, KEY)
    listed = providers.status()
    assert listed == [{"name": "ticketmaster", "configured": True,
                       "env_var": ticketmaster.ENV_VAR}]
    assert KEY not in repr(listed)


def test_an_unknown_provider_is_an_error():
    with pytest.raises(ValueError, match="unknown provider"):
        providers.get("myspace")


# ---- parsing a response ------------------------------------------------------

def test_a_documented_payload_normalises(keyed):
    items = ticketmaster.search(city="Lisbon", fetch=_fetch)["items"]
    assert [i["uid"] for i in items] == ["tm-1", "tm-2"]
    assert items[0]["title"] == "Nina Kraviz"
    assert items[0]["start"] == "2026-08-07T22:00:00Z"
    assert items[0]["place"] == "Lux Frágil" and items[0]["city"] == "Lisbon"


def test_a_date_only_listing_falls_back_to_localdate(keyed):
    items = ticketmaster.search(fetch=_fetch)["items"]
    assert items[1]["start"] == "2026-08-08"
    assert items[1]["city"] == "", "a venue with no city must not invent one"


def test_an_event_with_no_start_is_skipped_not_guessed_at():
    """The same refusal as RSS pubDate: an aggregator that invents a date is the thing this
    module must not become."""
    payload = {"_embedded": {"events": [
        {"id": "x", "name": "No date", "dates": {}},
        {"name": "No id", "dates": {"start": {"localDate": "2026-08-08"}}},
    ]}}
    assert ticketmaster.normalise(payload) == []


@pytest.mark.parametrize("payload", [
    {}, None, {"_embedded": {}}, {"_embedded": {"events": None}},
    {"_embedded": {"events": "not a list"}}, {"_embedded": {"events": ["string", 3]}},
    {"_embedded": {"events": [{"id": "a", "dates": {"start": {"localDate": "2026-08-08"}},
                               "_embedded": {"venues": []}}]}},
])
def test_a_payload_that_is_not_what_the_docs_say_does_not_crash(payload):
    assert isinstance(ticketmaster.normalise(payload), list)


def test_an_unreachable_api_is_a_status_not_a_raise(keyed):
    def boom(url, params):
        raise OSError("connection reset")
    result = ticketmaster.search(city="Lisbon", fetch=boom)
    assert result["status"].startswith("fetch failed") and result["items"] == []


def test_the_page_size_is_clamped(keyed):
    seen = {}

    def capture(url, params):
        seen.update(params)
        return PAYLOAD
    ticketmaster.search(size=9999, fetch=capture)
    assert seen["size"] == ticketmaster.MAX_SIZE


# ---- into the graph ----------------------------------------------------------

def test_provider_events_land_exactly_like_venue_feeds(graph, keyed, monkeypatch):
    monkeypatch.setattr(ticketmaster, "_fetch", _fetch)
    result = ingest.sync_provider(graph, "ticketmaster", city="Lisbon", now=TUE)
    assert result["added"] == 2

    system = Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER)
    rows = system.session("t", {"events:read"}).find_entities(
        "event", {"origin": "feed"}, limit=20)
    assert len(rows) == 2
    for row in rows:
        assert row["owner_id"] == SYSTEM_OWNER
        assert row["attrs"]["visibility"] == "public"
        assert row["attrs"]["provider"] == "ticketmaster"


def test_a_provider_listing_reads_as_listed(graph, keyed, monkeypatch):
    """The labelling condition applies to every tier, not just venue feeds."""
    from modules.weekend import digest
    monkeypatch.setattr(ticketmaster, "_fetch", _fetch)
    ingest.sync_provider(graph, "ticketmaster", city="Lisbon", now=TUE)
    assert "22:00 Nina Kraviz @ Lux Frágil · listed" in digest.weekend(
        graph, city="Lisbon", now=TUE)["text"]


def test_re_syncing_a_provider_updates_rather_than_duplicating(graph, keyed, monkeypatch):
    monkeypatch.setattr(ticketmaster, "_fetch", _fetch)
    ingest.sync_provider(graph, "ticketmaster", city="Lisbon", now=TUE)
    second = ingest.sync_provider(graph, "ticketmaster", city="Lisbon", now=TUE)
    assert (second["added"], second["updated"]) == (0, 2)


def test_a_provider_listing_cannot_collide_with_a_venue_feed(graph, keyed, monkeypatch):
    """Dedupe keys are namespaced, so a venue whose ICS uid happens to be `tm-1` does not
    overwrite the API's event."""
    monkeypatch.setattr(ticketmaster, "_fetch", _fetch)
    monkeypatch.setattr(ingest, "_fetch", lambda url: (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:tm-1\nSUMMARY:Venue's own\n"
        "DTSTART:20260807T230000Z\nDTEND:20260808T060000Z\nEND:VEVENT\nEND:VCALENDAR\n"))
    ingest.sync_provider(graph, "ticketmaster", city="Lisbon", now=TUE)
    feed = ingest.add_feed(graph, "https://lux.example/e.ics", city="Lisbon")["feed_id"]
    ingest.sync(graph, feed, now=TUE)

    system = Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER)
    titles = {r["attrs"]["title"] for r in system.session("t", {"events:read"}).find_entities(
        "event", {"origin": "feed"}, limit=20)}
    assert {"Nina Kraviz", "Venue's own"} <= titles


def test_the_horizon_applies_to_providers_too(graph, keyed, monkeypatch):
    monkeypatch.setattr(ticketmaster, "_fetch", lambda url, params: {"_embedded": {"events": [
        {"id": "old", "name": "Last year", "dates": {"start": {"localDate": "2024-08-08"}}}]}})
    result = ingest.sync_provider(graph, "ticketmaster", city="Lisbon", now=TUE)
    assert result["added"] == 0 and result["skipped_out_of_range"] == 1


# ---- the gateway -------------------------------------------------------------

def test_the_endpoints_work(cfg, monkeypatch):
    monkeypatch.setenv(ticketmaster.ENV_VAR, KEY)
    # Every other test here pins the clock with `now=TUE` and can use PAYLOAD as written.
    # This one goes through HTTP, which has no clock seam, so its listings have to be dated
    # relative to today or the test expires a couple of days after it is written.
    monkeypatch.setattr(ticketmaster, "_fetch", _payload_relative)
    client = TestClient(create_app(cfg))

    listed = client.get("/v1/feeds/providers").json()["providers"]
    assert listed[0]["name"] == "ticketmaster" and listed[0]["configured"] is True
    assert KEY not in client.get("/v1/feeds/providers").text

    r = client.post("/v1/feeds/providers/ticketmaster/sync", json={"city": "Lisbon"})
    assert r.status_code == 200 and r.json()["added"] == 2


def test_an_unconfigured_provider_is_200_with_a_status_not_an_error(cfg, unkeyed):
    client = TestClient(create_app(cfg))
    r = client.post("/v1/feeds/providers/ticketmaster/sync", json={"city": "Lisbon"})
    assert r.status_code == 200 and r.json()["status"] == "not_configured"


def test_an_unknown_provider_is_a_400(cfg):
    client = TestClient(create_app(cfg))
    assert client.post("/v1/feeds/providers/myspace/sync", json={}).status_code == 400
