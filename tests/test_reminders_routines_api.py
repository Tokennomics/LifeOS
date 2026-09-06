"""Reminders and crew routines over HTTP.

The isolation test lives here rather than beside the module: reminders are owner-scoped, and
a module-level test shares one Graph between both accounts, so it would pass for the wrong
reason. Only the gateway builds a per-account graph, so only here does "your reminders are
yours" mean anything.
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
    for name in ("ana", "bruno", "carla"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    made = client.post("/v1/crews", json={"name": "the regulars", "visibility": "private"},
                       headers=people["ana"]["h"]).json()
    crew_id = made.get("id") or made.get("crew_id")
    client.post("/v1/crews/invite",
                json={"crew_id": crew_id, "person_id": people["bruno"]["id"]},
                headers=people["ana"]["h"])
    client.post("/v1/crews/invite/accept", json={"crew_id": crew_id},
                headers=people["bruno"]["h"])
    return client, people, crew_id


# ---- reminders ---------------------------------------------------------------

def test_a_reminder_is_stored_and_listed(world):
    client, people, _ = world
    out = client.post("/v1/notifications/schedule",
                      json={"text": "stretch", "at": "08:00"},
                      headers=people["ana"]["h"]).json()
    assert out["set"] is True
    assert out["push_delivered"] is False

    listed = client.get("/v1/notifications", headers=people["ana"]["h"]).json()
    assert [r["text"] for r in listed["reminders"]] == ["stretch"]


def test_your_reminders_are_yours(world):
    """Owner-scoped, and only the gateway builds a per-account graph — which is why this
    test lives here and not beside the module."""
    client, people, _ = world
    client.post("/v1/notifications/schedule", json={"text": "stretch", "at": "08:00"},
                headers=people["ana"]["h"])
    assert client.get("/v1/notifications",
                      headers=people["bruno"]["h"]).json()["empty"] is True
    assert client.get("/v1/notifications/due",
                      headers=people["bruno"]["h"]).json()["empty"] is True


def test_a_reminder_can_be_cancelled(world):
    client, people, _ = world
    out = client.post("/v1/notifications/schedule",
                      json={"text": "stretch", "at": "08:00"},
                      headers=people["ana"]["h"]).json()
    client.post("/v1/notifications/cancel", json={"reminder_id": out["reminder_id"]},
                headers=people["ana"]["h"])
    assert client.get("/v1/notifications",
                      headers=people["ana"]["h"]).json()["empty"] is True


def test_you_cannot_cancel_somebody_elses(world):
    client, people, _ = world
    out = client.post("/v1/notifications/schedule",
                      json={"text": "stretch", "at": "08:00"},
                      headers=people["ana"]["h"]).json()
    res = client.post("/v1/notifications/cancel",
                      json={"reminder_id": out["reminder_id"]},
                      headers=people["bruno"]["h"])
    assert res.status_code == 400
    assert client.get("/v1/notifications",
                      headers=people["ana"]["h"]).json()["empty"] is False


def test_a_bad_time_is_refused(world):
    client, people, _ = world
    res = client.post("/v1/notifications/schedule", json={"text": "x", "at": "8am"},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "not a time" in res.json()["detail"]


def test_nothing_anywhere_claims_a_notification_was_sent(world):
    client, people, _ = world
    client.post("/v1/notifications/schedule", json={"text": "stretch", "at": "08:00"},
                headers=people["ana"]["h"])
    for path in ("/v1/notifications", "/v1/notifications/due"):
        body = client.get(path, headers=people["ana"]["h"]).json()
        assert body["push_delivered"] is False
        assert body["delivery_note"]


# ---- crew routines -----------------------------------------------------------

def test_a_routine_is_set_and_listed_with_real_dates(world):
    client, people, crew_id = world
    out = client.post("/v1/routines/squad-sync",
                      json={"crew_id": crew_id, "title": "dawn patrol",
                            "day": "wed", "at": "07:00", "place": "Carcavelos"},
                      headers=people["ana"]["h"]).json()
    assert out["recurrence"] == "every wed at 07:00"
    assert len(out["upcoming"]) == 4

    listed = client.get(f"/v1/crews/{crew_id}/routines",
                        headers=people["bruno"]["h"]).json()
    assert listed["routines"][0]["title"] == "dawn patrol"
    assert len(listed["routines"][0]["next"]) == 4


def test_the_routine_claims_no_calendar_was_touched(world):
    """`synced_calendars: 5` on a crew that might have had none, and an ics_link on a host
    this deployment does not serve."""
    client, people, crew_id = world
    res = client.post("/v1/routines/squad-sync",
                      json={"crew_id": crew_id, "title": "dawn patrol",
                            "day": "wed", "at": "07:00"},
                      headers=people["ana"]["h"])
    out = res.json()
    assert out["calendars_synced"] == 0
    assert out["can_subscribe"] == 2
    assert "connectos.app" not in res.text
    assert out["ics_path"] == f"/v1/crews/{crew_id}/export.ics"


def test_the_ics_link_it_gives_you_actually_serves_the_routine(world):
    """The old one pointed at somebody else's domain. This one is fetched here, and the
    standing session is in it."""
    client, people, crew_id = world
    out = client.post("/v1/routines/squad-sync",
                      json={"crew_id": crew_id, "title": "dawn patrol",
                            "day": "wed", "at": "07:00", "place": "Carcavelos"},
                      headers=people["ana"]["h"]).json()
    feed = client.get(out["ics_path"], headers=people["ana"]["h"])
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in feed.text
    assert "dawn patrol" in feed.text


def test_a_calendar_app_can_actually_fetch_the_feed(world):
    """The subscribe link is the whole point of a recurring routine, and the authenticated
    .ics route 401s for everything except the signed-in app — a calendar client has no way
    to send a bearer token. So the URL is the credential."""
    client, people, crew_id = world
    client.post("/v1/routines/squad-sync",
                json={"crew_id": crew_id, "title": "dawn patrol", "day": "wed",
                      "at": "07:00"},
                headers=people["ana"]["h"])
    link = client.post(f"/v1/crews/{crew_id}/calendar-link", json={},
                       headers=people["ana"]["h"]).json()

    # No Authorization header at all — exactly what a calendar client sends.
    feed = client.get(link["subscribe_path"])
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("text/calendar")
    assert "dawn patrol" in feed.text


def test_the_feed_link_is_read_only_and_reveals_nothing_else(world):
    client, people, crew_id = world
    link = client.post(f"/v1/crews/{crew_id}/calendar-link", json={},
                       headers=people["ana"]["h"]).json()
    assert link["read_only"] is True
    # It is not a login: it opens a calendar, not the account that minted it.
    assert client.get("/v1/notifications",
                      headers={"Authorization": f"Bearer {link['token']}"}
                      ).status_code == 401


def test_a_revoked_feed_link_stops_working(world):
    client, people, crew_id = world
    client.post("/v1/routines/squad-sync",
                json={"crew_id": crew_id, "title": "dawn patrol", "day": "wed",
                      "at": "07:00"},
                headers=people["ana"]["h"])
    link = client.post(f"/v1/crews/{crew_id}/calendar-link", json={},
                       headers=people["ana"]["h"]).json()
    client.post("/v1/crews/calendar-link/revoke", json={"feed_id": link["feed_id"]},
                headers=people["ana"]["h"])
    feed = client.get(link["subscribe_path"])
    assert feed.status_code == 200            # a calendar, just an empty one
    assert "dawn patrol" not in feed.text


def test_an_unknown_feed_token_is_indistinguishable_from_a_revoked_one(world):
    """Same empty calendar either way, so the URL space cannot be probed for live crews."""
    client, _, _ = world
    feed = client.get("/calendar/not-a-real-token.ics")
    assert feed.status_code == 200
    assert "BEGIN:VCALENDAR" in feed.text
    assert "VEVENT" not in feed.text


def test_a_non_member_cannot_mint_a_feed_link(world):
    client, people, crew_id = world
    assert client.post(f"/v1/crews/{crew_id}/calendar-link", json={},
                       headers=people["carla"]["h"]).status_code == 400


def test_a_routine_with_no_title_or_a_bad_day_is_refused(world):
    client, people, crew_id = world
    for body in ({"crew_id": crew_id, "day": "wed", "at": "07:00"},
                 {"crew_id": crew_id, "title": "x", "day": "someday", "at": "07:00"},
                 {"crew_id": crew_id, "title": "x", "day": "wed", "at": "7am"}):
        res = client.post("/v1/routines/squad-sync", json=body,
                          headers=people["ana"]["h"])
        assert res.status_code == 400
        assert "Dawn Patrol" not in res.text


def test_a_non_member_cannot_read_or_set_a_routine(world):
    client, people, crew_id = world
    client.post("/v1/routines/squad-sync",
                json={"crew_id": crew_id, "title": "dawn patrol", "day": "wed",
                      "at": "07:00"},
                headers=people["ana"]["h"])
    assert client.get(f"/v1/crews/{crew_id}/routines",
                      headers=people["carla"]["h"]).status_code == 400
    assert client.post("/v1/routines/squad-sync",
                       json={"crew_id": crew_id, "title": "mine now", "day": "thu",
                             "at": "09:00"},
                       headers=people["carla"]["h"]).status_code == 400


def test_ending_a_routine_removes_it_from_the_feed(world):
    client, people, crew_id = world
    out = client.post("/v1/routines/squad-sync",
                      json={"crew_id": crew_id, "title": "dawn patrol", "day": "wed",
                            "at": "07:00"},
                      headers=people["ana"]["h"]).json()
    client.post("/v1/routines/squad-sync/end",
                json={"routine_id": out["routine_id"]}, headers=people["ana"]["h"])
    feed = client.get(out["ics_path"], headers=people["ana"]["h"])
    assert "dawn patrol" not in feed.text


def test_the_emergency_card_endpoint_the_pwa_calls_exists(world):
    """The PWA asked for `/v1/triage/critical` on every page load and when saving. The
    route is `/v1/triage/card` — so the emergency card silently 404'd both ways, and a
    card somebody believed they had saved was never stored.
    """
    import pathlib
    client, people, _ = world
    app_js = (pathlib.Path(__file__).resolve().parent.parent
              / "surfaces" / "app" / "www" / "app.js").read_text(encoding="utf-8")
    assert "/v1/triage/critical" not in app_js

    saved = client.post("/v1/triage/card",
                        json={"full_name": "Ana", "blood_type": "O-",
                              "allergies": "penicillin"},
                        headers=people["ana"]["h"])
    assert saved.status_code == 200
    read = client.get("/v1/triage/card", headers=people["ana"]["h"]).json()
    # The card comes back inside an envelope, which the PWA was also reading wrongly — it
    # took the fields off the top level, so every box stayed empty even with the right URL.
    assert read["card"]["blood_type"] == "O-"
    assert "(m.critical && m.critical.card)" in app_js
