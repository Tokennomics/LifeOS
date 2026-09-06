"""Venue feeds into the graph: ownership, dedupe, bounds, and failure that stays local."""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.feeds import ingest
from modules.weekend import digest
from substrate import SYSTEM_OWNER
from substrate.graph import Graph

PW = "correct-horse-battery"
TUE = "2026-08-04T09:00:00+00:00"
URL = "https://lux.example/events.ics"

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:lux-1
SUMMARY:Warehouse party
DTSTART:20260807T230000Z
DTEND:20260808T060000Z
LOCATION:Cais do Sodré
END:VEVENT
BEGIN:VEVENT
UID:lux-2
SUMMARY:Sunday session
DTSTART:20260809T160000Z
DTEND:20260809T220000Z
END:VEVENT
END:VCALENDAR
"""


def ics_relative(*day_offsets):
    """An ICS whose events sit a fixed number of days from *today*.

    `ICS` above is pinned to real dates, which is fine everywhere it is passed with
    `now=TUE` — those tests carry their own clock and stay deterministic forever. Tests that
    go through the gateway or the scheduler have no clock seam: they run against the real
    `datetime.now()`. With absolute dates they pass on the day they are written and then
    silently rot, failing once the calendar walks past `ingest.STALE_DAYS` — which is
    exactly what happened, three days after these were written, to six tests at once.

    A test that only passes in the week it was authored is not testing the horizon, it is
    testing the wall clock. Offsets keep it honest.
    """
    when = datetime.datetime.now(datetime.timezone.utc)
    events = "".join(
        "BEGIN:VEVENT\nUID:rel-{i}\nSUMMARY:Night {i}\nDTSTART:{s}\nDTEND:{e}\n"
        "LOCATION:Cais do Sodré\nEND:VEVENT\n".format(
            i=i,
            s=(when + datetime.timedelta(days=offset)).strftime("%Y%m%dT%H%M%SZ"),
            e=(when + datetime.timedelta(days=offset, hours=3)).strftime("%Y%m%dT%H%M%SZ"))
        for i, offset in enumerate(day_offsets))
    return "BEGIN:VCALENDAR\n" + events + "END:VCALENDAR\n"


ICS_SOON = ics_relative(1, 2)


@pytest.fixture
def world(graph):
    ana = accounts.register(graph, "ana", PW)
    bruno = accounts.register(graph, "bruno", PW)
    return {"ana": Graph(graph.conn, graph.bus, default_owner=ana["owner_id"]),
            "bruno": Graph(graph.conn, graph.bus, default_owner=bruno["owner_id"]),
            "root": graph}


def _add(g, url=URL, **kw):
    return ingest.add_feed(g, url, city=kw.get("city", "Lisbon"),
                           venue=kw.get("venue", "Lux"), topic=kw.get("topic", "techno"))


def _system_events(world):
    system = Graph(world["root"].conn, world["root"].bus, default_owner=SYSTEM_OWNER)
    return system.session("t", {"events:read"}).find_entities(
        "event", {"origin": "feed"}, limit=100)


# ---- subscribing -------------------------------------------------------------

def test_adding_a_feed_fetches_nothing(world):
    """Adding must never block on a slow server — sync is a separate act."""
    result = _add(world["ana"])
    assert result["added"] is True
    assert ingest.feeds(world["ana"])[0]["last_status"] == "never synced"


def test_adding_the_same_feed_twice_is_idempotent(world):
    first = _add(world["ana"])
    again = _add(world["ana"])
    assert again["added"] is False and again["feed_id"] == first["feed_id"]


@pytest.mark.parametrize("bad", ["", "   ", "lux.example/e.ics", "ftp://x/y", "javascript:x"])
def test_a_feed_needs_a_real_url(world, bad):
    with pytest.raises(ValueError):
        ingest.add_feed(world["ana"], bad)


def test_your_subscriptions_are_yours(world):
    _add(world["ana"])
    assert len(ingest.feeds(world["ana"])) == 1
    assert ingest.feeds(world["bruno"]) == []


# ---- syncing -----------------------------------------------------------------

def test_syncing_creates_public_system_owned_events(world):
    feed = _add(world["ana"])["feed_id"]
    result = ingest.sync(world["ana"], feed, text=ICS, now=TUE)
    assert result["added"] == 2

    rows = _system_events(world)
    assert len(rows) == 2
    for row in rows:
        assert row["owner_id"] == SYSTEM_OWNER, "one city's listings exist once, not per account"
        assert row["attrs"]["visibility"] == "public"
        assert row["attrs"]["city"] == "Lisbon"
        assert row["attrs"]["venue"] == "Lux"
        assert row["attrs"]["origin"] == "feed"


def test_the_events_are_visible_to_an_account_that_never_added_the_feed(world):
    """The subscription is yours; the listing is everyone's."""
    ingest.sync(world["ana"], _add(world["ana"])["feed_id"], text=ICS, now=TUE)
    d = digest.weekend(world["bruno"], city="Lisbon", now=TUE)
    assert [i["title"] for i in d["days"][0]["open"]] == ["Warehouse party"]


def test_re_syncing_updates_rather_than_duplicating(world):
    feed = _add(world["ana"])["feed_id"]
    ingest.sync(world["ana"], feed, text=ICS, now=TUE)
    second = ingest.sync(world["ana"], feed, text=ICS, now=TUE)
    assert (second["added"], second["updated"]) == (0, 2)
    assert len(_system_events(world)) == 2


def test_two_people_subscribing_to_one_venue_do_not_double_the_city(world):
    """Dedupe is keyed on (url, uid) and deliberately does NOT include who subscribed."""
    ingest.sync(world["ana"], _add(world["ana"])["feed_id"], text=ICS, now=TUE)
    ingest.sync(world["bruno"], _add(world["bruno"])["feed_id"], text=ICS, now=TUE)
    assert len(_system_events(world)) == 2


def test_a_changed_title_is_picked_up_on_the_next_sync(world):
    feed = _add(world["ana"])["feed_id"]
    ingest.sync(world["ana"], feed, text=ICS, now=TUE)
    ingest.sync(world["ana"], feed, text=ICS.replace("Warehouse party", "Warehouse party (moved)"),
                now=TUE)
    assert "Warehouse party (moved)" in {r["attrs"]["title"] for r in _system_events(world)}


def test_the_feed_records_its_own_last_status(world):
    feed = _add(world["ana"])["feed_id"]
    ingest.sync(world["ana"], feed, text=ICS, now=TUE)
    row = ingest.feeds(world["ana"])[0]
    assert row["last_status"].startswith("ok: 2 added")
    assert row["last_count"] == 2 and row["last_synced_at"]


# ---- bounds ------------------------------------------------------------------

def test_the_archive_is_not_imported(world):
    """A venue feed containing its whole history would otherwise import its whole history."""
    old = ICS.replace("20260807T230000Z", "20240807T230000Z").replace(
        "20260809T160000Z", "20240809T160000Z")
    result = ingest.sync(world["ana"], _add(world["ana"])["feed_id"], text=old, now=TUE)
    assert result["added"] == 0 and result["skipped_out_of_range"] == 2


def test_dates_far_in_the_future_are_skipped(world):
    far = ICS.replace("20260807T230000Z", "20300807T230000Z")
    result = ingest.sync(world["ana"], _add(world["ana"])["feed_id"], text=far, now=TUE)
    assert result["added"] == 1 and result["skipped_out_of_range"] == 1


def test_dateless_rss_items_are_counted_not_smuggled_in(world):
    rss = """<rss><channel>
      <item><title>Announcement</title><link>a</link>
        <pubDate>Tue, 04 Aug 2026 09:00:00 GMT</pubDate></item>
    </channel></rss>"""
    result = ingest.sync(world["ana"], _add(world["ana"])["feed_id"], text=rss, now=TUE)
    assert result["skipped_no_date"] == 1 and result["added"] == 0
    assert _system_events(world) == []


def test_a_feed_cannot_flood_the_graph(world):
    many = "BEGIN:VCALENDAR\n" + "".join(
        f"BEGIN:VEVENT\nUID:e{i}\nSUMMARY:Night {i}\n"
        f"DTSTART:20260807T2300{i % 60:02d}Z\nDTEND:20260808T0600{i % 60:02d}Z\nEND:VEVENT\n"
        for i in range(ingest.MAX_ITEMS + 50)) + "END:VCALENDAR\n"
    result = ingest.sync(world["ana"], _add(world["ana"])["feed_id"], text=many, now=TUE)
    assert result["added"] == ingest.MAX_ITEMS


# ---- failure stays local -----------------------------------------------------

def test_a_dead_venue_is_recorded_not_raised(world, monkeypatch):
    monkeypatch.setattr(ingest, "_fetch",
                        lambda url: (_ for _ in ()).throw(OSError("connection refused")))
    result = ingest.sync(world["ana"], _add(world["ana"])["feed_id"], now=TUE)
    assert result["status"] == "fetch_failed" and result["added"] == 0
    assert "fetch failed" in ingest.feeds(world["ana"])[0]["last_status"]


def test_one_bad_feed_does_not_stop_the_others(world, monkeypatch):
    good = _add(world["ana"])["feed_id"]
    _add(world["ana"], url="https://dead.example/e.ics", venue="Dead")

    def fetch(url):
        if "dead" in url:
            raise OSError("nope")
        return ICS_SOON
    monkeypatch.setattr(ingest, "_fetch", fetch)

    result = ingest.sync_all(world["ana"])
    assert result["feeds"] == 2 and result["added"] == 2
    assert {r["status"] for r in result["results"]} == {"ok", "fetch_failed"}


def test_syncing_an_unknown_feed_is_an_error(world):
    with pytest.raises(ValueError):
        ingest.sync(world["ana"], "not-a-feed", text=ICS)


def test_removing_a_feed_keeps_the_listings_it_already_published(world):
    """Unsubscribing is not a retraction — other accounts may be looking at those events."""
    feed = _add(world["ana"])["feed_id"]
    ingest.sync(world["ana"], feed, text=ICS, now=TUE)
    ingest.remove_feed(world["ana"], feed)
    assert len(_system_events(world)) == 2
    assert ingest.sync_all(world["ana"])["feeds"] == 0


# ---- how it reads ------------------------------------------------------------

def test_a_listing_is_labelled_as_a_listing(world):
    """A scraped club night and 'six people from your crew agreed' are different promises."""
    ingest.sync(world["ana"], _add(world["ana"])["feed_id"], text=ICS, now=TUE)
    text = digest.weekend(world["ana"], city="Lisbon", now=TUE)["text"]
    assert "23:00 Warehouse party @ Cais do Sodré · listed" in text


def test_a_crew_night_is_not_labelled_as_a_listing(world):
    from modules.discover import discover
    discover.publish_event(world["bruno"], "Sushi night", start="2026-08-08T20:00:00+00:00",
                           city="Lisbon", place="Bairro Alto", visibility="public")
    text = digest.weekend(world["ana"], city="Lisbon", now=TUE)["text"]
    assert "Sushi night @ Bairro Alto" in text and "Sushi night @ Bairro Alto · listed" not in text


# ---- the gateway -------------------------------------------------------------

def test_the_endpoints_work(cfg):
    client = TestClient(create_app(cfg))
    added = client.post("/v1/feeds", json={"url": URL, "city": "Lisbon", "venue": "Lux"})
    assert added.status_code == 200
    feed_id = added.json()["feed_id"]

    synced = client.post(f"/v1/feeds/{feed_id}/sync", json={"text": ICS_SOON})
    assert synced.status_code == 200 and synced.json()["added"] == 2
    assert client.get("/v1/feeds").json()["feeds"][0]["venue"] == "Lux"
    assert client.delete(f"/v1/feeds/{feed_id}").json()["removed"] is True


def test_a_bad_url_is_a_400_not_a_500(cfg):
    client = TestClient(create_app(cfg))
    assert client.post("/v1/feeds", json={"url": "not-a-url"}).status_code == 400
