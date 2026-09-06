"""Arrival — what a new user sees ten seconds after signing in, and who is around.

The listings half is composition and mostly needs to not fall over. The half that needs care
is the presence marker: "this person is in this city right now" is structured, durable and
answers exactly the question somebody dangerous would ask, so announcing has to be an
explicit act and never a side effect of using the app.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import arrival, chat

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def travellers(cfg):
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


def _arrive(client, who, city="Lisbon"):
    return client.get(f"/v1/city/arrival?city={city}", headers=who["h"]).json()


# ---- the empty case, which is the normal one ----------------------------------

def test_an_empty_city_says_what_to_do_rather_than_nothing(travellers):
    """A young instance is empty, and an empty screen with no next step is how it loses the
    person who could have started its first crew."""
    client, people = travellers
    body = _arrive(client, people["ana"])
    assert body["empty"] is True
    assert "you are the first" in body["suggestion"].lower()
    assert body["around"] == [] and body["crews"] == []


def test_one_request_answers_the_whole_screen(travellers):
    """Six round trips on hotel wifi is the difference between a product and a spinner."""
    client, people = travellers
    body = _arrive(client, people["ana"])
    for key in ("around", "crews", "events", "venue_feeds", "recent_chat",
                "you_are_here", "empty", "suggestion"):
        assert key in body


def test_a_broken_module_does_not_blank_the_screen(travellers, monkeypatch):
    """Every part degrades on its own. An empty city is the normal case, not an error, and
    one raising module must not take the arrival screen with it."""
    from modules.crews import crews

    def boom(*a, **kw):
        raise RuntimeError("directory is down")
    monkeypatch.setattr(crews, "directory", boom)

    body = _arrive(client=travellers[0], who=travellers[1]["ana"])
    assert body["crews"] == [] and "label" in body


# ---- announcing is always explicit --------------------------------------------

def test_reading_or_posting_does_not_announce_you(travellers):
    """The one that matters. Using the room must never publish that you are in the city."""
    client, people = travellers
    client.get("/v1/city/chat?city=Lisbon", headers=people["ana"]["h"])
    client.post("/v1/city/chat", headers=people["ana"]["h"],
                json={"city": "Lisbon", "text": "hello"})

    assert _arrive(client, people["bruno"])["around"] == []
    assert _arrive(client, people["ana"])["you_are_here"] is False


def test_announcing_shows_you_to_other_travellers(travellers):
    client, people = travellers
    assert client.post("/v1/city/around", headers=people["ana"]["h"], json={
        "city": "Lisbon", "note": "here till Sunday, up for climbing",
        "days": 3}).status_code == 200

    seen = _arrive(client, people["bruno"])["around"]
    assert [p["handle"] for p in seen] == ["ana"]
    assert seen[0]["note"] == "here till Sunday, up for climbing"
    assert _arrive(client, people["ana"])["you_are_here"] is True


def test_withdrawing_is_immediate(travellers):
    client, people = travellers
    client.post("/v1/city/around", headers=people["ana"]["h"], json={"city": "Lisbon"})
    assert len(_arrive(client, people["bruno"])["around"]) == 1

    client.request("DELETE", "/v1/city/around", headers=people["ana"]["h"],
                   json={"city": "Lisbon"})
    assert _arrive(client, people["bruno"])["around"] == []


def test_re_announcing_replaces_rather_than_stacks(travellers):
    """Otherwise updating your note lists you three times."""
    client, people = travellers
    for note in ("first", "second", "third"):
        client.post("/v1/city/around", headers=people["ana"]["h"],
                    json={"city": "Lisbon", "note": note})

    seen = _arrive(client, people["bruno"])["around"]
    assert len(seen) == 1 and seen[0]["note"] == "third"


def test_presence_expires(graph, monkeypatch):
    """Durable presence is a standing answer to 'is this person here'. It has to lapse."""
    arrival.announce(graph, "Lisbon", account_id="acct-1", handle="ana", days=2)
    assert len(arrival.around(graph, "Lisbon")) == 1

    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
    monkeypatch.setattr(arrival, "_now", lambda: later)
    assert arrival.around(graph, "Lisbon") == []


@pytest.mark.parametrize("days", [0, -1, arrival.MAX_DAYS + 1, 400])
def test_the_window_is_bounded(travellers, days):
    client, people = travellers
    assert client.post("/v1/city/around", headers=people["ana"]["h"],
                       json={"city": "Lisbon", "days": days}).status_code == 400


def test_a_note_is_length_capped(travellers):
    client, people = travellers
    client.post("/v1/city/around", headers=people["ana"]["h"],
                json={"city": "Lisbon", "note": "x" * 5000})
    assert len(_arrive(client, people["bruno"])["around"][0]["note"]) <= arrival.MAX_NOTE


def test_presence_never_carries_more_than_a_city(travellers):
    """City granularity is what makes this safe. No coordinates, no venue, no 'online now'."""
    client, people = travellers
    client.post("/v1/city/around", headers=people["ana"]["h"],
                json={"city": "Lisbon", "note": "hi"})
    person = _arrive(client, people["bruno"])["around"][0]
    assert set(person) == {"account_id", "handle", "note", "since", "mine"}
    for forbidden in ("lat", "lon", "email", "venue", "address", "last_seen"):
        assert forbidden not in repr(person).lower()


def test_you_cannot_announce_as_someone_else(travellers):
    client, people = travellers
    client.post("/v1/city/around", headers=people["mallory"]["h"], json={
        "city": "Lisbon", "note": "meet me alone", "account_id": people["ana"]["id"]})
    seen = _arrive(client, people["bruno"])["around"]
    assert [p["handle"] for p in seen] == ["mallory"]


def test_announcing_needs_a_session(cfg):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    assert client.post("/v1/city/around", json={"city": "Lisbon"}).status_code == 401


# ---- muting carries across ------------------------------------------------------

def test_someone_you_muted_in_the_room_is_not_offered_as_company(travellers):
    """Muting is 'I do not want this person in my experience', not 'I do not want their
    chat messages'. Reappearing in a list of people to meet would defeat it."""
    client, people = travellers
    client.post("/v1/city/around", headers=people["mallory"]["h"],
                json={"city": "Lisbon", "note": "around all week"})
    assert len(_arrive(client, people["ana"])["around"]) == 1

    client.post("/v1/city/chat/mute", headers=people["ana"]["h"],
                json={"target_id": people["mallory"]["id"]})
    assert _arrive(client, people["ana"])["around"] == []
    # ...and only for the person who muted.
    assert len(_arrive(client, people["bruno"])["around"]) == 1


# ---- the listings half ----------------------------------------------------------

def test_arrival_shows_what_is_actually_in_the_city(travellers):
    client, people = travellers
    client.post("/v1/crews", headers=people["ana"]["h"], json={
        "name": "Lisbon Climbers", "city": "Lisbon", "visibility": "public",
        "admission": "open"})
    client.post("/v1/city/chat", headers=people["ana"]["h"],
                json={"city": "Lisbon", "text": "anyone out tonight?"})

    body = _arrive(client, people["bruno"])
    assert body["empty"] is False and body["suggestion"] == ""
    assert "Lisbon Climbers" in repr(body["crews"])
    assert "anyone out tonight?" in repr(body["recent_chat"])


@pytest.mark.parametrize("spelling", ["Lisbon", "lisbon", " LISBON "])
def test_arrival_and_the_room_agree_on_the_city(travellers, spelling):
    client, people = travellers
    client.post("/v1/city/around", headers=people["ana"]["h"], json={"city": "Lisbon"})
    body = client.get(f"/v1/city/arrival?city={spelling.strip()}",
                      headers=people["bruno"]["h"]).json()
    assert body["city"] == chat.slug("Lisbon")
    assert len(body["around"]) == 1
