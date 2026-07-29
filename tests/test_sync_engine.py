import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.calendar import sync_engine
from substrate.graph import Graph

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar//EN
BEGIN:VEVENT
SUMMARY:Google Developer Summit
DTSTART:20260810T100000Z
LOCATION:Lisbon Tech Hub
END:VEVENT
END:VCALENDAR"""


def test_ics_feed_import(graph: Graph):
    res = sync_engine.import_ics_feed(graph, SAMPLE_ICS)
    assert res["imported_count"] == 1
    event = res["events"][0]
    assert event["title"] == "Google Developer Summit"
    assert event["location"] == "Lisbon Tech Hub"


def test_gateway_calendar_sync_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {"ics_content": SAMPLE_ICS}
    resp = client.post("/v1/calendar/sync-import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["imported_count"] == 1
