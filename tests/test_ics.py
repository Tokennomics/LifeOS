import datetime

from modules.calendars import freebusy

SAMPLE_ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:evt-1@example.com\r
DTSTART:20260720T090000Z\r
DTEND:20260720T100000Z\r
SUMMARY:Standup with a very long title that fol\r
 ds across two lines\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:evt-2@example.com\r
DTSTART;TZID=Australia/Brisbane:20260721T180000\r
DTEND;TZID=Australia/Brisbane:20260721T190000\r
SUMMARY:Dinner\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:evt-3@example.com\r
DTSTART;VALUE=DATE:20260722\r
DTEND;VALUE=DATE:20260723\r
SUMMARY:All day thing\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_parse_ics_formats_and_folding():
    events = freebusy.parse_ics(SAMPLE_ICS, default_tz="UTC")
    assert len(events) == 3
    by_uid = {e["uid"]: e for e in events}
    assert by_uid["evt-1@example.com"]["start"] == "2026-07-20T09:00:00+00:00"
    assert by_uid["evt-1@example.com"]["title"].endswith("folds across two lines")
    assert by_uid["evt-2@example.com"]["start"].startswith("2026-07-21T18:00:00+10:00")
    assert by_uid["evt-3@example.com"]["start"].startswith("2026-07-22T00:00:00")


def test_sync_upserts_by_uid_and_respects_privacy(graph, cfg):
    now = datetime.datetime(2026, 7, 19, tzinfo=datetime.timezone.utc)
    first = freebusy.sync(graph, cfg, ics_text=SAMPLE_ICS, now=now)
    assert first == {"status": "ok", "events": 3}
    second = freebusy.sync(graph, cfg, ics_text=SAMPLE_ICS, now=now)
    assert second["events"] == 3

    s = graph.session("calendars", freebusy.SCOPES)
    events = s.find_entities("event")
    assert len(events) == 3  # upserted, not duplicated
    assert all(e["attrs"]["busy"] for e in events)
    assert all("title" not in e["attrs"] for e in events)  # store_titles defaults false


def test_sync_window_filters_far_events(graph, cfg):
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)  # events are in July
    result = freebusy.sync(graph, cfg, ics_text=SAMPLE_ICS, now=now)
    assert result["events"] == 0


def test_sync_not_configured(graph, cfg):
    assert freebusy.sync(graph, cfg)["status"] == "not-configured"
