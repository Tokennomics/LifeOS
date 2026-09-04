"""Four handlers that answered from a dictionary, and now answer from the city or not at all.

`/events/landmark-radar` branched on the city name: Edinburgh got the Fringe, the Tattoo and
a gin distillery with `VIP_FAST_PASS`; Munich got Oktoberfest and "6M Visitors"; anything
else got "City Cultural Mega-Fest — Seasonal". `/travel/layover-discovery` returned one
Munich itinerary whatever you asked about, with a gate alarm "Armed for 14:15".
`/memories/analog-film-swap` reported a synced film roll and twelve scans nobody made.
`/simulation/*` scored the app 98/100 and 98.4/100 on behalf of six people who do not exist.
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


# ---- landmark radar ----------------------------------------------------------

def test_the_radar_reads_the_map_and_an_unseeded_city_is_empty(world):
    """No network in tests, so nothing is seeded and the true answer is nothing — with a
    sentence saying which of the two things is missing."""
    client, people = world
    res = client.post("/v1/events/landmark-radar", json={"city": "Edinburgh"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["places"] == [] and body["empty"] is True
    assert body["bearings"] is False and body["distances"] is False
    assert body["suggestion"]
    for invented in ("fringe", "tattoo", "oktoberfest", "mega-fest", "vip_fast_pass",
                     "ai_butler_synchronized"):
        assert invented not in res.text.lower()


def test_the_radar_shows_the_places_a_city_actually_has(world):
    """Seeded the way `tests/test_city_guide.py` seeds one: through `places.seed` with an
    injected Overpass response, because outbound network is off in tests."""
    from modules.city import places
    client, people = world
    payload = {"elements": [{"type": "node", "id": 4242, "lat": 55.94, "lon": -3.19,
                             "tags": {"name": "The Meadows"}}]}
    places.seed(client.app.state.graph, "Edinburgh", category="park",
                geocode_fetch=lambda u, p: {"results": [
                    {"name": "Edinburgh", "country": "United Kingdom",
                     "latitude": 55.95, "longitude": -3.18}]},
                overpass_fetch=lambda u, q: payload)

    res = client.post("/v1/events/landmark-radar", json={"city": "Edinburgh"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    assert [row["name"] for row in res.json()["places"]] == ["The Meadows"]
    assert res.json()["empty"] is False


def test_the_radar_asks_for_a_city_rather_than_defaulting_edinburgh(world):
    client, people = world
    res = client.post("/v1/events/landmark-radar", json={}, headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.json()["needs_city"] is True and res.json()["empty"] is True
    assert "edinburgh" not in res.text.lower()


# ---- layover -----------------------------------------------------------------

def test_a_layover_answers_about_the_city_you_name(world):
    client, people = world
    res = client.post("/v1/travel/layover-discovery",
                      json={"city": "Munich", "hours": 5}, headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["city"] == "munich"
    assert body["hours"] == 5                      # an input, echoed, not judged
    assert body["alarm_set"] is False
    assert body["empty"] is True and body["places"] == []
    # By key where the honest copy names what it disclaims ("nothing is armed"), by text
    # for the invented itinerary itself.
    for invented in ("curated_micro_escape", "safe_exploration_time",
                     "gate_return_alarm", "transit_hub", "layover_navigator_active"):
        assert invented not in body
    for invented in ("eisbachwelle", "s8 express", "isartor", "pretzel"):
        assert invented not in res.text.lower()


def test_a_layover_with_no_city_asks_instead_of_picking_one(world):
    client, people = world
    res = client.post("/v1/travel/layover-discovery", json={"layover_hours": 4.5},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.json()["needs_city"] is True
    assert res.json()["hours"] == 4.5
    assert "munich" not in res.text.lower()


# ---- the film swap -----------------------------------------------------------

def test_the_film_swap_is_a_complementary_match_and_scans_nothing(world):
    client, people = world
    res = client.post("/v1/memories/analog-film-swap",
                      json={"city": "Lisbon", "offering": "portra", "seeking": "hp5"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["matched"] is False and body["people"] == []
    assert body["photos"] is False
    for invented in ("film_roll_synced", "photos_scanned", "shared_album_url",
                     "film_stock", "outing_id"):
        assert invented not in body
    assert "connectos.app" not in res.text


def test_the_film_swap_needs_both_halves_of_the_swap(world):
    client, people = world
    res = client.post("/v1/memories/analog-film-swap", json={"city": "Lisbon"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.json()["matched"] is False
    assert "offering" in res.json()["suggestion"]


def test_the_film_swap_finds_somebody_who_wants_what_you_have(world):
    """The mirror: what you offer against what they want, both ways."""
    client, people = world
    client.post("/v1/synergy/open-to",
                json={"city": "Lisbon", "activity": "hp5", "offers": "hp5",
                      "wants": "portra"}, headers=people["bruno"]["h"])
    res = client.post("/v1/memories/analog-film-swap",
                      json={"city": "Lisbon", "offering": "portra", "seeking": "hp5"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["matched"] is True
    assert [person["handle"] for person in body["people"]] == ["bruno"]


# ---- the simulations ---------------------------------------------------------

@pytest.mark.parametrize("path,payload", [
    ("/v1/simulation/full-day-ux-optimizer", {"persona": "Digital Nomad",
                                              "city": "Edinburgh"}),
    ("/v1/simulation/multi-demographic-suite", {"profile": "ALL"}),
])
def test_a_simulation_reports_that_it_cannot_and_scores_nothing(world, path, payload):
    """The ticket allowed either a real in-process sweep of the routes or `available:
    False`. This takes the second: a sweep run inside a request would be the process calling
    itself several hundred times with this route in the list, and it would still not be a
    simulation of a person. `tools/sweep_endpoints.py` does the real thing from outside."""
    client, people = world
    res = client.post(path, json=payload, headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False and body["scored"] is False
    assert body["why"] and body["needs"]
    assert "sweep_endpoints" in body["suggestion"]
    for invented in ("simulation_metrics", "simulated_24h_timeline",
                     "universal_ux_score", "dopamine_vitality_score",
                     "profiles_evaluated", "suite_simulation_complete",
                     "simulation_complete"):
        assert invented not in body
    for number in ("98/100", "98.4", "12.5 minutes", "4.5 hours"):
        assert number not in res.text.lower()
    assert "score" not in str(body.get("requested", ""))
