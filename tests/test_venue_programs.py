"""A venue's programme board: rows people posted, not two literals.

`GET /venues/programs` returned a bouldering league and a coffee cupping, the same two on
every deployment, each with a perk the venue had never agreed to. `POST /venues/program`
answered `published: True`, stored nothing, and defaulted the venue, the title and the
schedule — so an empty body published a programme for a climbing gym nobody had spoken to.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.venues import programs

PW = "correct-horse-battery"


def _soon(days: int = 3, hour: int = 19) -> str:
    when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    return when.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


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


# ---- the module --------------------------------------------------------------

def test_an_entry_is_stored_and_read_back(graph):
    made = programs.publish(graph, "Lisbon", venue="A Bakery", title="Cupping morning",
                            starts_at=_soon(), account_id="acct-1", handle="ana")
    assert made["published"] is True and made["official"] is False

    out = programs.listing(graph, "Lisbon")
    assert out["count"] == 1
    entry = out["programs"][0]
    assert entry["venue"] == "A Bakery" and entry["title"] == "Cupping morning"
    assert entry["posted_by"] == "acct-1" and entry["posted_by_handle"] == "ana"


def test_a_city_with_nothing_on_it_is_empty_and_says_what_would_fill_it(graph):
    out = programs.listing(graph, "Porto")
    assert out["programs"] == [] and out["empty"] is True
    assert "venues/program" in out["suggestion"]


def test_the_venue_the_title_and_the_time_are_all_required(graph):
    for kwargs in ({"venue": "", "title": "Cupping", "starts_at": _soon()},
                   {"venue": "A Bakery", "title": "", "starts_at": _soon()},
                   {"venue": "A Bakery", "title": "Cupping", "starts_at": ""}):
        with pytest.raises(programs.ProgramError):
            programs.publish(graph, "Lisbon", account_id="acct-1", **kwargs)
    with pytest.raises(programs.ProgramError):
        programs.publish(graph, "", venue="A Bakery", title="Cupping",
                         starts_at=_soon(), account_id="acct-1")


def test_a_finished_entry_drops_off_the_board(graph):
    long_ago = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(days=30)).isoformat()
    made = programs.publish(graph, "Lisbon", venue="A Bakery", title="Old one",
                            starts_at=_soon(), account_id="acct-1")
    # Rewrite the row's start into the past: publishing one directly is refused, which is
    # itself the point of the check above.
    from substrate import SYSTEM_OWNER
    from substrate.graph import Graph
    session = Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(
        programs.MODULE, programs.SCOPES)
    session.update_entity(made["program_id"], {"starts_at": long_ago}, source="test")
    assert programs.listing(graph, "Lisbon")["count"] == 0


def test_only_whoever_posted_it_can_take_it_down(graph):
    made = programs.publish(graph, "Lisbon", venue="A Bakery", title="Cupping",
                            starts_at=_soon(), account_id="acct-1")
    with pytest.raises(programs.ProgramError):
        programs.withdraw(graph, made["program_id"], account_id="acct-2")
    programs.withdraw(graph, made["program_id"], account_id="acct-1")
    assert programs.listing(graph, "Lisbon")["empty"] is True


# ---- over HTTP ---------------------------------------------------------------

def test_a_new_instance_has_no_programmes_and_names_none(world):
    client, people = world
    res = client.get("/v1/venues/programs?city=Lisbon", headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["programs"] == [] and body["empty"] is True
    for invented in ("fabrica", "vertical wall", "15%", "perks"):
        assert invented not in res.text.lower()


def test_publishing_then_reading_shows_the_entry_that_was_published(world):
    client, people = world
    res = client.post("/v1/venues/program",
                      json={"city": "Lisbon", "venue": "A Bakery",
                            "title": "Cupping morning", "starts_at": _soon()},
                      headers=people["ana"]["h"])
    assert res.status_code == 200 and res.json()["published"] is True

    listed = client.get("/v1/venues/programs?city=Lisbon", headers=people["bruno"]["h"])
    assert listed.status_code == 200
    entries = listed.json()["programs"]
    assert [entry["title"] for entry in entries] == ["Cupping morning"]
    assert entries[0]["posted_by_handle"] == "ana"


def test_an_empty_body_publishes_nothing(world):
    """The default venue, title and schedule are gone: without a city there is nothing to
    publish into, and without a venue and a title there is nothing to publish."""
    client, people = world
    res = client.post("/v1/venues/program", json={}, headers=people["ana"]["h"])
    assert res.status_code == 400
    for invented in ("vertical wall", "bouldering", "tuesdays"):
        assert invented not in res.text.lower()


def test_the_route_is_the_programme_route_not_the_venue_details_route(world):
    """`/venues/programs` sits before `/venues/{place_id}`, which would otherwise swallow it
    and serve every call as a venue lookup for place_id="programs"."""
    client, people = world
    res = client.get("/v1/venues/programs?city=Lisbon", headers=people["ana"]["h"])
    assert res.status_code == 200
    assert "programs" in res.json()


def test_without_a_city_it_asks_rather_than_guessing_one(world):
    client, people = world
    res = client.get("/v1/venues/programs", headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.json()["needs_city"] is True and res.json()["empty"] is True
