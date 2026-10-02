"""Your calendar and LifeOS, both ways.

Out: a personal subscribe link carries your own LifeOS events and nothing else. The token
is shown once and stored hashed, expires, can be revoked, and an unknown token gets an
empty calendar. Busy blocks imported from your calendar are not echoed back.

In: a pasted secret iCal address becomes free/busy blocks. Titles are kept only on
request, a cancelled meeting disappears, and the day planner stops planning over them.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.agent import day
from modules.calendars import personal
from substrate.graph import Graph

NOW = datetime.datetime(2026, 10, 7, 9, 0, tzinfo=datetime.timezone.utc)


def _ics(*events):
    body = "".join(
        f"BEGIN:VEVENT\nUID:{uid}\nSUMMARY:{title}\nDTSTART:{start}\nDTEND:{end}\nEND:VEVENT\n"
        for uid, title, start, end in events)
    return f"BEGIN:VCALENDAR\n{body}END:VCALENDAR\n"


@pytest.fixture(autouse=True)
def _no_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


# ---- out ------------------------------------------------------------------------------

def test_a_link_opens_only_your_own_events(graph):
    graph.session("t", {"events:write"}).create_entity("event", {
        "title": "Fado night", "start": "2026-10-10T21:00:00+00:00", "origin": "agent_plan"},
        source="t")
    Graph(graph.conn, graph.bus, default_owner="someone-else").session(
        "t", {"events:write"}).create_entity("event", {
            "title": "Their dentist", "start": "2026-10-10T10:00:00+00:00"}, source="t")
    link = personal.mint_link(graph)
    ics = personal.feed(graph, link["token"])
    assert "Fado night" in ics and "Their dentist" not in ics


def test_the_token_is_stored_hashed(graph):
    link = personal.mint_link(graph)
    stored = str(personal._sys(graph).find_entities("content", {"type": personal.LINK_RECORD}))
    assert link["token"] not in stored and personal._hash(link["token"]) in stored


def test_unknown_revoked_and_expired_tokens_get_an_empty_calendar(graph, monkeypatch):
    graph.session("t", {"events:write"}).create_entity("event", {
        "title": "Mine", "start": "2026-10-10T21:00:00+00:00"}, source="t")
    link = personal.mint_link(graph)
    assert "Mine" not in personal.feed(graph, "not-a-token")
    personal.revoke_link(graph, link["link_id"])
    assert "Mine" not in personal.feed(graph, link["token"])
    other = personal.mint_link(graph, days=1)
    monkeypatch.setattr(personal, "_now", lambda: datetime.datetime.now(
        datetime.timezone.utc) + datetime.timedelta(days=3))
    assert "Mine" not in personal.feed(graph, other["token"])


def test_imported_busy_blocks_are_not_echoed_back(graph):
    src = personal.add_source(graph, "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics")
    personal.sync_source(graph, src["source_id"], now=NOW, text=_ics(
        ("m1", "Board meeting", "20261008T100000Z", "20261008T110000Z")))
    ics = personal.feed(graph, personal.mint_link(graph)["token"])
    assert "Busy" not in ics and "Board meeting" not in ics


# ---- in ---------------------------------------------------------------------------------

def test_busy_times_without_titles_by_default(graph):
    src = personal.add_source(graph, "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics")
    out = personal.sync_source(graph, src["source_id"], now=NOW, text=_ics(
        ("m1", "Divorce lawyer", "20261008T100000Z", "20261008T110000Z"),
        ("m2", "Far future", "20271008T100000Z", "20271008T110000Z")))
    assert out["busy_blocks"] == 1
    events = graph.session("t", {"events:read"}).find_entities("event", {"source": personal.IMPORTED})
    assert [e["attrs"]["title"] for e in events] == ["Busy"]
    assert "Divorce lawyer" not in str(events)


def test_a_cancelled_meeting_disappears(graph):
    src = personal.add_source(graph, "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics")
    two = _ics(("m1", "A", "20261008T100000Z", "20261008T110000Z"),
               ("m2", "B", "20261009T100000Z", "20261009T110000Z"))
    personal.sync_source(graph, src["source_id"], now=NOW, text=two)
    out = personal.sync_source(graph, src["source_id"], now=NOW, text=_ics(
        ("m1", "A", "20261008T100000Z", "20261008T110000Z")))
    assert out["removed"] == 1
    assert len(graph.session("t", {"events:read"}).find_entities(
        "event", {"source": personal.IMPORTED})) == 1


def test_the_secret_address_is_never_shown_whole(graph):
    url = "https://calendar.google.com/calendar/ical/me%40x.com/private-0123456789abcdef/basic.ics"
    personal.add_source(graph, url)
    shown = personal.sources(graph)[0]["calendar"]
    assert "0123456789abcdef" not in shown and shown.startswith("https://calendar.google.com/")


@pytest.mark.parametrize("bad", ["http://calendar.example/x.ics", "ftp://x/y", "not a url"])
def test_only_https_or_webcal_addresses(graph, bad):
    with pytest.raises(personal.CalendarError):
        personal.add_source(graph, bad)


def test_webcal_is_accepted_as_https(graph):
    out = personal.add_source(graph, "webcal://p01-calendars.icloud.com/published/2/abc")
    assert out["calendar"].startswith("https://p01-calendars.icloud.com/")


def test_removing_a_calendar_removes_its_busy_blocks(graph):
    src = personal.add_source(graph, "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics")
    personal.sync_source(graph, src["source_id"], now=NOW, text=_ics(
        ("m1", "A", "20261008T100000Z", "20261008T110000Z")))
    assert personal.remove_source(graph, src["source_id"])["busy_blocks_removed"] == 1


def test_the_day_planner_does_not_plan_over_your_meetings(graph):
    src = personal.add_source(graph, "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics")
    personal.sync_source(graph, src["source_id"], now=NOW, text=_ics(
        ("m1", "Work dinner", "20261010T200000Z", "20261010T230000Z")))
    busy = day._busy(graph, datetime.date(2026, 10, 10))
    assert len(busy) == 1 and busy[0][2] == "Busy"


def test_the_refresh_loop_covers_every_account(graph, monkeypatch):
    other = Graph(graph.conn, graph.bus, default_owner="acct-other")
    personal.add_source(other, "https://calendar.google.com/calendar/ical/y/private-def/basic.ics")
    personal.add_source(graph, "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics")
    from substrate import safefetch
    monkeypatch.setattr(safefetch, "fetch_text", lambda url, **k: _ics())
    out = personal.sync_all(graph)
    assert out["calendars"] == 2 and out["ok"] == 2


# ---- routes ----------------------------------------------------------------------------

def test_the_routes(cfg, monkeypatch):
    client = TestClient(create_app(cfg))
    link = client.post("/v1/calendar/link").json()
    assert link["path"].startswith("/calendar/me/")
    feed = client.get(link["path"])
    assert feed.status_code == 200 and feed.text.startswith("BEGIN:VCALENDAR")
    assert client.get("/calendar/me/nope.ics").text.count("BEGIN:VEVENT") == 0
    from substrate import safefetch
    monkeypatch.setattr(safefetch, "fetch_text", lambda url, **k: _ics(
        ("m1", "A", "20991008T100000Z", "20991008T110000Z")))
    src = client.post("/v1/calendar/sources",
                      json={"url": "https://calendar.google.com/calendar/ical/x/private-abc/basic.ics"})
    assert src.status_code == 200
    assert client.post(f"/v1/calendar/sources/{src.json()['source_id']}/sync").json()["status"] == "ok"
    assert client.get("/v1/calendar/sources").json()["sources"][0]["last_status"].startswith("ok")
    assert client.post("/v1/calendar/sources", json={"url": "http://x/y"}).status_code == 400
