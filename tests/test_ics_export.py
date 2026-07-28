import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.calendars import export
from substrate.graph import Graph


def test_generate_ics_format(graph: Graph):
    session = graph.session("test", {"*"})
    session.create_entity(
        "event",
        {
            "title": "Climbing Night",
            "start": "2026-08-01T18:00:00Z",
            "end": "2026-08-01T20:00:00Z",
            "place": "Lisbon Bouldering Gym",
            "description": "Weekly group climbing session",
        },
        source="test",
    )

    ics_content = export.export_user_ics(graph)
    assert "BEGIN:VCALENDAR" in ics_content
    assert "VERSION:2.0" in ics_content
    assert "SUMMARY:Climbing Night" in ics_content
    assert "LOCATION:Lisbon Bouldering Gym" in ics_content
    assert "DESCRIPTION:Weekly group climbing session" in ics_content
    assert "DTSTART:20260801T180000Z" in ics_content
    assert "DTEND:20260801T200000Z" in ics_content
    assert "END:VCALENDAR" in ics_content


def test_gateway_calendar_export_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    # 1. User calendar export
    resp = client.get("/v1/calendar/export.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in resp.text

    # 2. Crew calendar export
    resp_crew = client.get("/v1/crews/crew-123/export.ics")
    assert resp_crew.status_code == 200
    assert resp_crew.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in resp_crew.text
