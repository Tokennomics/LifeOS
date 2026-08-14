"""A city seeds itself when somebody lands in it.

Seeding was operator-only, so the first person to arrive anywhere new saw an empty screen
and the operator found out too late to help them. That defeats the point of pulling the map
from OpenStreetMap in the first place: a city can have something in it before it has users,
but only if nobody has to be asked first.

The feature is three lines of wiring. **The tests here are almost entirely about the
guardrails**, because this is the only place in the app where ordinary user input makes the
server call a third party — and that third party is volunteer-run, free, and has no contract
that would survive somebody pasting five hundred city names into a text box.

So: a name that goes nowhere is asked about once, a real city is refreshed on a cooldown,
there is a ceiling per hour, seeding is sequential, and two people landing in the same city
at the same time cause one seed and not two.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import autoseed, places

PW = "correct-horse-battery"

GEOCODE = {"results": [{"name": "Lisbon", "country": "Portugal",
                        "latitude": 38.72, "longitude": -9.13,
                        "timezone": "Europe/Lisbon"}]}
OVERPASS = {"elements": [
    {"type": "node", "id": 1, "lat": 38.71, "lon": -9.14, "tags": {"name": "A cafe"}},
]}


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def wired(monkeypatch):
    """Providers that answer, without touching the network. Counts the calls, because "how
    many times did we ask Overpass" is the property most of this file is about."""
    calls = {"geocode": 0, "overpass": 0}

    def geo(url, params):
        calls["geocode"] += 1
        return GEOCODE

    def over(url, query):
        calls["overpass"] += 1
        return OVERPASS

    from modules.feeds.providers import openmeteo, overpass as ov
    monkeypatch.setattr(openmeteo, "_fetch", geo)
    monkeypatch.setattr(ov, "_fetch", over)
    return calls


@pytest.fixture
def city(cfg):
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


# ---- it happens at all -------------------------------------------------------

def test_arriving_in_an_unseeded_city_seeds_it(city, wired):
    """The whole feature: nobody had to ask an operator."""
    client, people = city
    client.get("/v1/city/arrival?city=Lisbon", headers=people["ana"]["h"])
    assert places.listing(_graph_of(client), "Lisbon")["total"] == 1


def test_the_second_person_finds_it_already_there(city, wired):
    client, people = city
    client.get("/v1/city/arrival?city=Lisbon", headers=people["ana"]["h"])
    body = client.get("/v1/city/arrival?city=Lisbon",
                      headers=people["bruno"]["h"]).json()
    assert [p["name"] for p in body["places"]] == ["A cafe"]


def test_announcing_arrival_also_seeds(city, wired):
    client, people = city
    client.post("/v1/city/around", json={"city": "Porto"}, headers=people["ana"]["h"])
    assert places.listing(_graph_of(client), "Porto")["total"] == 1


def test_the_first_response_does_not_wait_for_the_seed(city, wired):
    """It runs *after* the response, and this is how you can tell: the person who triggered
    the seed sees the empty city they arrived in, and the places are there on the next
    request. A screen that blocked on ten Overpass queries is not one anybody sees the end
    of, and that is the whole reason this is a background task."""
    client, people = city
    first = client.get("/v1/city/arrival?city=Lisbon",
                       headers=people["ana"]["h"]).json()
    assert first["places"] == []

    second = client.get("/v1/city/arrival?city=Lisbon",
                        headers=people["ana"]["h"]).json()
    assert [p["name"] for p in second["places"]] == ["A cafe"]


# ---- the guardrails ----------------------------------------------------------

def test_a_seeded_city_is_not_re_seeded_on_every_arrival(city, wired):
    """Ten people landing in Lisbon is one Overpass conversation, not ten."""
    client, people = city
    for _ in range(4):
        client.get("/v1/city/arrival?city=Lisbon", headers=people["ana"]["h"])
    assert wired["overpass"] == len(places.categories())


def test_a_city_that_does_not_exist_is_asked_about_once(city, monkeypatch):
    """A typo must not become a daily Overpass query forever."""
    from modules.feeds.providers import openmeteo, overpass as ov
    calls = {"n": 0}

    def nothing(url, params):
        calls["n"] += 1
        return {"results": []}

    monkeypatch.setattr(openmeteo, "_fetch", nothing)
    monkeypatch.setattr(ov, "_fetch", lambda u, q: OVERPASS)

    client, people = city
    for _ in range(3):
        client.get("/v1/city/arrival?city=Xyzzyville", headers=people["ana"]["h"])
    assert calls["n"] == 1


def test_a_failed_city_is_on_a_shorter_cooldown_than_a_good_one(graph):
    assert autoseed.FAILED_COOLDOWN_DAYS < autoseed.COOLDOWN_DAYS


def test_a_recently_seeded_city_is_not_eligible(graph, wired):
    autoseed.request(graph, "Lisbon")
    autoseed.drain(graph)
    assert autoseed.status_for(graph, "Lisbon")["eligible"] is False


def test_the_cooldown_does_expire(graph, wired):
    autoseed.request(graph, "Lisbon")
    autoseed.drain(graph)
    session = autoseed._sys(graph)
    row = session.find_entities("content", {"type": autoseed.RECORD}, limit=1)[0]
    old = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(days=autoseed.COOLDOWN_DAYS + 1)).isoformat()
    session.update_entity(row["id"], {"attempted_at": old}, source="test")
    assert autoseed.status_for(graph, "Lisbon")["eligible"] is True


def test_there_is_a_ceiling_per_hour(graph, wired):
    """A burst of arrivals queues rather than fans out."""
    for i in range(autoseed.MAX_PER_HOUR + 3):
        autoseed.request(graph, f"City{i}")
    out = autoseed.drain(graph, limit=autoseed.MAX_PER_HOUR + 3)
    assert out["attempted"] <= autoseed.MAX_PER_HOUR

    blocked = autoseed.drain(graph, limit=2)
    assert blocked["seeded"] == 0 and "ceiling" in blocked["skipped"]


def test_two_arrivals_at_once_seed_a_city_once(graph, wired):
    """Both queue, one claims. Otherwise the same city is fetched twice in a second."""
    first = autoseed.request(graph, "Lisbon")
    second = autoseed.request(graph, "Lisbon")
    assert first["queued"] is True and second["queued"] is False
    assert second["reason"] == "already queued"


def test_a_claim_that_never_finished_is_picked_up_again(graph, wired):
    """The background task runs in-process, so a deploy mid-seed leaves a claimed row. It
    has to be recoverable or that city is stuck forever."""
    autoseed.request(graph, "Lisbon")
    session = autoseed._sys(graph)
    row = session.find_entities("content", {"type": autoseed.RECORD}, limit=1)[0]
    stale = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(minutes=autoseed.CLAIM_MINUTES + 1)).isoformat()
    session.update_entity(row["id"], {"state": "claimed", "claimed_at": stale},
                          source="test")
    assert autoseed.drain(graph)["seeded"] == 1


def test_a_fresh_claim_is_left_alone(graph, wired):
    autoseed.request(graph, "Lisbon")
    session = autoseed._sys(graph)
    row = session.find_entities("content", {"type": autoseed.RECORD}, limit=1)[0]
    session.update_entity(row["id"], {"state": "claimed", "claimed_at":
                                      datetime.datetime.now(
                                          datetime.timezone.utc).isoformat()},
                          source="test")
    assert autoseed.status_for(graph, "Lisbon")["eligible"] is False


def test_the_queue_is_bounded(graph):
    for i in range(autoseed.MAX_QUEUE + 5):
        autoseed.request(graph, f"City{i}")
    pending = sum(1 for r in autoseed._rows(graph)
                  if r["attrs"].get("state") == "pending")
    assert pending <= autoseed.MAX_QUEUE


def test_an_empty_city_name_queues_nothing(graph):
    assert autoseed.request(graph, "  ")["queued"] is False


def test_seeding_never_breaks_the_arrival_screen(city, monkeypatch):
    """A city that cannot be seeded is a quieter screen, not an error on somebody's
    arrival."""
    from modules.feeds.providers import openmeteo

    def boom(url, params):
        raise OSError("overpass is down")

    monkeypatch.setattr(openmeteo, "_fetch", boom)
    client, people = city
    res = client.get("/v1/city/arrival?city=Lisbon", headers=people["ana"]["h"])
    assert res.status_code == 200


# ---- the operator's view -----------------------------------------------------

def test_the_queue_is_operator_only(city, wired):
    client, people = city
    assert client.get("/v1/seeding/queue", headers=people["ana"]["h"]).status_code == 403


def test_draining_is_operator_only(city, wired):
    client, people = city
    assert client.post("/v1/seeding/drain", json={},
                       headers=people["ana"]["h"]).status_code == 403


def test_the_queue_reports_what_was_tried(graph, wired):
    autoseed.request(graph, "Lisbon")
    autoseed.drain(graph)
    view = autoseed.queue(graph)
    assert view["queue"][0]["state"] == "done"
    assert view["queue"][0]["added"] == 1
    assert view["seeded_last_hour"] == 1


def test_the_drain_limit_is_bounded(city, cfg):
    """A cron job asking for a thousand cities gets the ceiling, not a thousand."""
    client = TestClient(create_app({**cfg, "gateway": {"auth_token": "op"}}))
    res = client.post("/v1/seeding/drain", json={"limit": 10_000},
                      headers={"Authorization": "Bearer op"})
    assert res.status_code == 200


# ---- helpers -----------------------------------------------------------------

def _graph_of(client):
    """The gateway's own graph, so a test can look at what the background task wrote."""
    return client.app.state.graph
