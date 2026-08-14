"""Meetups — the object that turns a message in the room into an actual meeting.

The interesting cases are not "a meetup is created". They are: who is allowed to say they
organised it, what happens when the organiser drops out, what a stranger can see before
deciding to go, and whether last week's plans are still cluttering tonight's list.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import meetups

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def city(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno", "mallory"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {
            "h": headers,
            "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


def _soon(hours=4):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=hours)).isoformat()


def _propose(client, who, title="Sunset at the viewpoint", city="Lisbon", **kw):
    body = {"city": city, "title": title, "starts_at": kw.pop("starts_at", _soon()),
            "place": kw.pop("place", "Miradouro"), **kw}
    return client.post("/v1/city/meetups", headers=who["h"], json=body)


def _list(client, who, city="Lisbon"):
    return client.get(f"/v1/city/meetups?city={city}", headers=who["h"]).json()


# ---- the point ------------------------------------------------------------------

def test_a_stranger_can_see_a_plan_and_join_it(city):
    """The whole gap this closes: in the room, "sunset at seven?" is a sentence that scrolls
    away and can only be answered with "me too"."""
    client, people = city
    assert _propose(client, people["ana"]).status_code == 200

    listed = _list(client, people["bruno"])["meetups"]
    assert len(listed) == 1
    assert listed[0]["title"] == "Sunset at the viewpoint"
    assert listed[0]["place"] == "Miradouro"
    assert listed[0]["organiser_handle"] == "ana"

    joined = client.post("/v1/city/meetups/join", headers=people["bruno"]["h"],
                         json={"meetup_id": listed[0]["meetup_id"]})
    assert joined.status_code == 200 and joined.json()["going"] == 2


def test_you_can_see_who_is_coming_before_you_decide(city):
    """Deciding whether to spend an evening with strangers needs more than a count."""
    client, people = city
    made = _propose(client, people["ana"]).json()
    client.post("/v1/city/meetups/join", headers=people["bruno"]["h"],
                json={"meetup_id": made["meetup_id"]})

    listed = _list(client, people["mallory"])["meetups"][0]
    assert sorted(p["handle"] for p in listed["going"]) == ["ana", "bruno"]
    assert listed["going_count"] == 2
    assert listed["you_are_going"] is False


def test_the_organiser_is_counted_as_going(city):
    """An attendee list that starts at zero reads as an idea nobody backs."""
    client, people = city
    _propose(client, people["ana"])
    listed = _list(client, people["ana"])["meetups"][0]
    assert listed["going_count"] == 1 and listed["you_are_going"] is True
    assert listed["yours"] is True


def test_plans_are_listed_soonest_first(city):
    client, people = city
    _propose(client, people["ana"], title="Later", starts_at=_soon(10))
    _propose(client, people["ana"], title="Sooner", starts_at=_soon(2))
    assert [m["title"] for m in _list(client, people["bruno"])["meetups"]] == \
        ["Sooner", "Later"]


def test_a_plan_you_joined_survives_looking_at_another_city(city):
    """A meetup joined in one room must not vanish the moment you open a different room."""
    client, people = city
    made = _propose(client, people["ana"], city="Porto").json()
    client.post("/v1/city/meetups/join", headers=people["bruno"]["h"],
                json={"meetup_id": made["meetup_id"]})

    mine = client.get("/v1/city/meetups/mine", headers=people["bruno"]["h"]).json()
    assert [m["title"] for m in mine["meetups"]] == ["Sunset at the viewpoint"]


# ---- organising as somebody else -------------------------------------------------

def test_you_cannot_organise_as_another_account(city):
    """'Ana is organising this' is a claim with real-world consequences."""
    client, people = city
    client.post("/v1/city/meetups", headers=people["mallory"]["h"], json={
        "city": "Lisbon", "title": "Come to my flat", "starts_at": _soon(),
        "organiser_id": people["ana"]["id"], "user_id": people["ana"]["id"]})

    listed = _list(client, people["bruno"])["meetups"]
    assert listed[0]["organiser_handle"] == "mallory"
    assert listed[0]["organiser_id"] == people["mallory"]["id"]


def test_only_the_organiser_can_call_it_off(city):
    client, people = city
    made = _propose(client, people["ana"]).json()
    from modules.city import meetups as m
    with pytest.raises(m.MeetupError):
        m.cancel(client.app.state.graph, made["meetup_id"],
                 account_id=people["mallory"]["id"])
    assert len(_list(client, people["bruno"])["meetups"]) == 1


def test_the_organiser_leaving_calls_it_off(city):
    """A plan whose author is not coming is not a plan, and letting the others find that out
    at the viewpoint is worse than cancelling."""
    client, people = city
    made = _propose(client, people["ana"]).json()
    client.post("/v1/city/meetups/join", headers=people["bruno"]["h"],
                json={"meetup_id": made["meetup_id"]})

    left = client.post("/v1/city/meetups/leave", headers=people["ana"]["h"],
                       json={"meetup_id": made["meetup_id"]})
    assert left.json()["cancelled"] is True
    assert _list(client, people["bruno"])["meetups"] == []


def test_an_attendee_leaving_does_not(city):
    client, people = city
    made = _propose(client, people["ana"]).json()
    client.post("/v1/city/meetups/join", headers=people["bruno"]["h"],
                json={"meetup_id": made["meetup_id"]})
    client.post("/v1/city/meetups/leave", headers=people["bruno"]["h"],
                json={"meetup_id": made["meetup_id"]})

    listed = _list(client, people["ana"])["meetups"]
    assert len(listed) == 1 and listed[0]["going_count"] == 1


# ---- safety --------------------------------------------------------------------

def test_the_safety_note_travels_with_every_meetup(city):
    """It belongs where somebody is deciding to go, not in a settings page they saw once."""
    client, people = city
    created = _propose(client, people["ana"]).json()
    assert "public" in created["safety_note"].lower()
    assert "public" in _list(client, people["bruno"])["safety_note"].lower()

    joined = client.post("/v1/city/meetups/join", headers=people["bruno"]["h"],
                         json={"meetup_id": created["meetup_id"]}).json()
    assert "public" in joined["safety_note"].lower()


def test_someone_you_muted_does_not_organise_your_evening(city):
    client, people = city
    _propose(client, people["mallory"], title="Come along")
    assert len(_list(client, people["ana"])["meetups"]) == 1

    client.post("/v1/city/chat/mute", headers=people["ana"]["h"],
                json={"target_id": people["mallory"]["id"]})
    assert _list(client, people["ana"])["meetups"] == []
    assert len(_list(client, people["bruno"])["meetups"]) == 1


def test_a_meetup_carries_no_location_finer_than_a_place_name(city):
    """City granularity is the promise the whole city surface makes, and a meetup is exactly
    where somebody would be tempted to break it."""
    client, people = city
    client.post("/v1/city/meetups", headers=people["ana"]["h"], json={
        "city": "Lisbon", "title": "Walk", "starts_at": _soon(),
        "place": "Miradouro", "lat": 38.7, "lon": -9.1, "address": "12 Rua X"})
    listed = _list(client, people["bruno"])["meetups"][0]
    for forbidden in ("lat", "lon", "address", "coordinates"):
        assert forbidden not in listed


def test_reading_and_organising_need_a_session(cfg):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    assert client.get("/v1/city/meetups?city=Lisbon").status_code == 401
    assert client.post("/v1/city/meetups", json={
        "city": "Lisbon", "title": "x", "starts_at": _soon()}).status_code == 401


# ---- bounds ---------------------------------------------------------------------

def test_last_night_s_plans_are_not_tonight_s_list(city):
    """A list that is mostly stale is worse than no list."""
    client, people = city
    _propose(client, people["ana"], title="Tonight")
    assert len(_list(client, people["bruno"])["meetups"]) == 1

    from modules.city import meetups as m
    later = (datetime.datetime.now(datetime.timezone.utc)
             + datetime.timedelta(hours=m.GRACE_HOURS + 6))
    import unittest.mock
    with unittest.mock.patch.object(m, "_now", lambda: later):
        assert m.listing(client.app.state.graph, "Lisbon")["meetups"] == []


def test_a_meetup_in_the_past_is_refused(city):
    client, people = city
    assert _propose(client, people["ana"], starts_at=_soon(-48)).status_code == 400


def test_a_meetup_absurdly_far_ahead_is_refused(city):
    client, people = city
    assert _propose(client, people["ana"],
                    starts_at=_soon(24 * (meetups.MAX_DAYS_AHEAD + 5))).status_code == 400


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_a_plan_needs_a_title(city, bad):
    client, people = city
    assert client.post("/v1/city/meetups", headers=people["ana"]["h"], json={
        "city": "Lisbon", "title": bad or "", "starts_at": _soon()}).status_code == 400


@pytest.mark.parametrize("bad", ["", "not a date", "tomorrow-ish"])
def test_a_plan_needs_a_real_time(city, bad):
    client, people = city
    assert _propose(client, people["ana"], starts_at=bad).status_code == 400


def test_a_naive_timestamp_is_read_as_utc_not_refused(graph):
    """Rejecting a missing timezone suffix means rejecting half the world's date pickers."""
    soon = (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=3)).replace(tzinfo=None).isoformat()
    made = meetups.create(graph, "Lisbon", title="Walk", starts_at=soon,
                          organiser_id="acct-1", organiser_handle="ana")
    assert made["meetup_id"]


def test_one_person_cannot_fill_the_list(city):
    client, people = city
    for i in range(meetups.MAX_PER_WINDOW):
        assert _propose(client, people["mallory"], title=f"Plan {i}").status_code == 200
    assert _propose(client, people["mallory"], title="Another").status_code == 400
    assert _propose(client, people["ana"], title="Mine").status_code == 200


def test_joining_something_already_over_is_refused(graph):
    made = meetups.create(graph, "Lisbon", title="Walk",
                          starts_at=(datetime.datetime.now(datetime.timezone.utc)
                                     + datetime.timedelta(hours=1)).isoformat(),
                          organiser_id="acct-1")
    later = (datetime.datetime.now(datetime.timezone.utc)
             + datetime.timedelta(hours=meetups.GRACE_HOURS + 4))
    import unittest.mock
    with unittest.mock.patch.object(meetups, "_now", lambda: later):
        with pytest.raises(meetups.MeetupError):
            meetups.join(graph, made["meetup_id"], account_id="acct-2")


def test_joining_twice_does_not_double_you(city):
    client, people = city
    made = _propose(client, people["ana"]).json()
    for _ in range(3):
        client.post("/v1/city/meetups/join", headers=people["bruno"]["h"],
                    json={"meetup_id": made["meetup_id"]})
    assert _list(client, people["ana"])["meetups"][0]["going_count"] == 2


def test_an_unknown_meetup_is_a_400_not_a_500(city):
    client, people = city
    assert client.post("/v1/city/meetups/join", headers=people["ana"]["h"],
                       json={"meetup_id": "not-a-real-id"}).status_code == 400
