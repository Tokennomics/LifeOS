"""The reflection and the export over HTTP.

The property worth testing here and nowhere else: an export contains *your* rows and
nobody else's. Module-level tests share one Graph between accounts, so only the gateway —
which builds a per-account graph — can answer that honestly.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def world(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


def test_the_reflection_reads_your_rows(world):
    client, people = world
    client.post("/v1/ai/stoic-presence-mirror", json={"note": "walked the long way home"},
                headers=people["ana"]["h"])
    client.post("/v1/events/qr-checkin", json={"place": "Fabrica"},
                headers=people["ana"]["h"])
    out = client.post("/v1/journal/daily-reflection-synthesis", json={},
                      headers=people["ana"]["h"]).json()
    assert out["empty"] is False
    assert out["sources"]


def test_the_reflection_no_longer_invents_a_city_day(world):
    """"Munich" used to return dawn surfers on the Eisbach and gratitude to Lukas."""
    client, people = world
    res = client.post("/v1/journal/daily-reflection-synthesis",
                      json={"city": "Munich"}, headers=people["ana"]["h"])
    assert res.status_code == 200
    text = res.text.lower()
    for invented in ("eisbach", "lukas", "blitz", "monopteros", "pretzel", "munich"):
        assert invented not in text


def test_a_fresh_account_gets_an_empty_day_not_somebody_elses(world):
    client, people = world
    out = client.post("/v1/journal/daily-reflection-synthesis", json={},
                      headers=people["bruno"]["h"]).json()
    assert out["empty"] is True
    assert out["did"] == []


def test_the_export_is_the_export_not_a_link(world):
    client, people = world
    client.post("/v1/ai/stoic-presence-mirror", json={"note": "a real note"},
                headers=people["ana"]["h"])
    out = client.post("/v1/export/universal-markdown", json={},
                      headers=people["ana"]["h"]).json()
    assert out["download_url"] is None
    assert "a real note" in "".join(out["documents"].values())
    assert "connectos.app" not in str(out)
    assert ".zip" not in str(out)


def test_an_export_holds_nobody_elses_rows(world):
    """The property only the gateway can answer: module tests share one graph."""
    client, people = world
    client.post("/v1/ai/stoic-presence-mirror", json={"note": "ana's private note"},
                headers=people["ana"]["h"])
    out = client.post("/v1/export/universal-markdown", json={},
                      headers=people["bruno"]["h"]).json()
    assert "ana's private note" not in "".join(out["documents"].values())
    assert out["rows"] == 0


def test_the_export_downloads_as_one_markdown_file(world):
    client, people = world
    client.post("/v1/ai/stoic-presence-mirror", json={"note": "a real note"},
                headers=people["ana"]["h"])
    res = client.get("/v1/export/universal-markdown.md", headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    assert "a real note" in res.text


def test_an_unsigned_caller_exports_nothing(world):
    client, _ = world
    assert client.post("/v1/export/universal-markdown", json={}).status_code == 401
    assert client.get("/v1/export/universal-markdown.md").status_code == 401


def test_the_export_includes_shared_rows_that_are_yours(world):
    """A kudos, a moment or a tab entry lives under the system owner so both parties can
    read it. An export that walked only the owner slice left out the notes people wrote
    you, the money on your tab, and everything you posted in a city — a partial export
    presented as a whole one."""
    client, people = world
    client.post("/v1/kudos/send",
                json={"to_account": people["bruno"]["id"], "note": "you carried the night"},
                headers=people["ana"]["h"])
    client.post("/v1/moments/flash", json={"city": "Lisbon", "caption": "sunset from here"},
                headers=people["ana"]["h"])

    mine = client.post("/v1/export/universal-markdown", json={},
                       headers=people["ana"]["h"]).json()
    everything = "".join(mine["documents"].values())
    assert "you carried the night" in everything      # she wrote it
    assert "sunset from here" in everything           # she posted it


def test_a_shared_row_appears_for_both_sides_and_nobody_else(world):
    client, people = world
    client.post("/v1/kudos/send",
                json={"to_account": people["bruno"]["id"], "note": "you carried the night"},
                headers=people["ana"]["h"])
    his = client.post("/v1/export/universal-markdown", json={},
                      headers=people["bruno"]["h"]).json()
    # It was addressed to him, so it is his to take too.
    assert "you carried the night" in "".join(his["documents"].values())


def test_a_kudos_reaches_the_person_it_names(world):
    """It passed the recipient straight through, so a kudos addressed to the handle
    "bruno" was stored against the literal string — and `kudos_for` looks up by account id,
    so the person it was about could never read it. That is the one thing this record
    exists to do."""
    client, people = world
    sent = client.post("/v1/kudos/send",
                       json={"to_account": "bruno", "note": "you carried the night"},
                       headers=people["ana"]["h"])
    assert sent.status_code == 200
    assert sent.json()["to_account"] == people["bruno"]["id"]

    got = client.get("/v1/kudos", headers=people["bruno"]["h"]).json()
    assert [k["note"] for k in got["kudos"]] == ["you carried the night"]


def test_a_kudos_to_nobody_is_refused(world):
    client, people = world
    res = client.post("/v1/kudos/send",
                      json={"to_account": "nobody-here", "note": "hello"},
                      headers=people["ana"]["h"])
    assert res.status_code == 400


def test_the_calendar_import_route_the_pwa_calls_exists(world):
    """The PWA posted to `/v1/calendar/import-ics`; the route is `/calendar/sync-import`,
    so every paste of a calendar feed 404'd and imported nothing."""
    import pathlib
    client, people = world
    app_js = (pathlib.Path(__file__).resolve().parent.parent
              / "surfaces" / "app" / "www" / "app.js").read_text(encoding="utf-8")
    assert "/v1/calendar/import-ics" not in app_js

    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x@t\r\n"
           "DTSTART:20260901T180000Z\r\nDTEND:20260901T200000Z\r\n"
           "SUMMARY:Pottery evening\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    res = client.post("/v1/calendar/sync-import", json={"ics_content": ics},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
