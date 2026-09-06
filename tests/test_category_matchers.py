"""Forty activity endpoints that were forty literals.

Nightlife, hobbies, wellness, dining, culture, swaps, festivals, creative, impact,
workshops, outdoors, music, pets, housing — every one of them answered "who else is up for
this?" with invented people, and several went further and claimed to have *booked*
something: a rooftop tasting with a named sommelier, a guestlist spot, a sauna, a supper
club hosted by Chef Lucas V.

They are all the same question, so they now all run the same matcher. The sweep at the top
of this file is the important test: it walks every one of them against an empty city and
requires an honest answer, because a single one left as a literal is a single one that will
tell somebody a stranger is waiting for them.

The rest pin the cases where the shape genuinely differs — swaps have to be mirrors, and a
handful map to real modules rather than to the matcher.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app

PW = "correct-horse-battery"

# path -> a body that names the activity in that endpoint's own vocabulary.
ACTIVITY_ENDPOINTS = {
    "/v1/nightlife/party-radar": {},
    "/v1/nightlife/secret-speakeasies": {"password": "knock twice"},
    "/v1/nightlife/guestlist-vip": {"venue": "the warehouse"},
    "/v1/nightlife/crew-pregame": {"destination": "the docks"},
    "/v1/hobbies/sports-outdoors": {"sport": "bouldering"},
    "/v1/hobbies/creative-making": {"craft": "ceramics"},
    "/v1/hobbies/gaming-strategy": {"game": "go"},
    "/v1/hobbies/culinary-craft": {"dish": "ramen"},
    "/v1/wellness/cold-plunge": {"beach": "the cove"},
    "/v1/wellness/sauna-social": {"venue": "the baths"},
    "/v1/wellness/digital-detox": {"duration": "2 hours"},
    "/v1/dining/market-cookoff": {"market": "the market"},
    "/v1/dining/wine-tasting": {"rooftop": "the terrace"},
    "/v1/dining/supper-club": {"cuisine": "tapas"},
    "/v1/culture/secret-comedy": {"venue": "the cellar"},
    "/v1/culture/silent-reading": {"loft": "the loft"},
    "/v1/culture/creator-residency": {"craft": "printmaking"},
    "/v1/economy/plant-swap": {"park": "the park"},
    "/v1/economy/community-borrow": {"item": "a tent"},
    "/v1/festivals/solo-camp-crew": {"festival_name": "the festival"},
    "/v1/festivals/carpool-split": {"festival_name": "the festival"},
    "/v1/festivals/stage-flare": {"stage_name": "main stage"},
    "/v1/creatives/pop-up-jam": {"instrument": "guitar"},
    "/v1/creatives/art-crawl": {"district": "the old town"},
    "/v1/impact/eco-clean-crew": {"beach": "the cove"},
    "/v1/impact/regenerative-earth": {},
    "/v1/impact/zero-waste-pantry": {},
    "/v1/impact/compassion-listener-network": {"vibe": "a hard week"},
    "/v1/impact/intergenerational-guild": {"skill": "carpentry"},
    "/v1/workshops/micro-masterclasses": {"skill": "welding"},
    "/v1/outdoors/sunset-sailing": {"harbor": "the marina"},
    "/v1/music/squad-jukebox": {"venue": "the bar"},
    "/v1/pets/dog-walk-crew": {"park": "the park"},
    "/v1/housing/co-living-match": {"budget": "900"},
}

SWAP_ENDPOINTS = {
    "/v1/economy/barter-swap": {"offering": "surf lesson", "seeking": "portuguese"},
    "/v1/economy/time-bank": {"offering": "carpentry", "service": "childcare"},
    "/v1/housing/nomad-house-swap": {"home_city": "lisbon", "destination_city": "tokyo"},
}

# Names that appeared in these handlers and must never appear again.
INVENTED = ["Elena", "Marcus", "Sophia", "Alex M.", "Chef Lucas", "Catriona", "Ewan",
            "Kirsty", "Hamish", "Isla", "Inês", "Julian", "Tiago", "Clara", "Leo V.",
            "Mateo", "Sarah Lin"]


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


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


# ---- the sweep ---------------------------------------------------------------

@pytest.mark.parametrize("path", sorted(ACTIVITY_ENDPOINTS))
def test_every_activity_endpoint_is_honest_when_the_city_is_empty(city, path):
    """One left as a literal is one that will tell somebody a stranger is waiting."""
    client, people = city
    res = client.post(path, json={"city": "Lisbon", **ACTIVITY_ENDPOINTS[path]},
                      headers=people["ana"]["h"])
    assert res.status_code == 200, path
    body = res.json()
    assert body["matched"] is False, path
    assert body["people"] == [], path


@pytest.mark.parametrize("path", sorted(ACTIVITY_ENDPOINTS))
def test_no_activity_endpoint_names_a_person_who_does_not_exist(city, path):
    client, people = city
    text = client.post(path, json={"city": "Lisbon", **ACTIVITY_ENDPOINTS[path]},
                       headers=people["ana"]["h"]).text
    for name in INVENTED:
        assert name not in text, f"{path} still names {name}"


@pytest.mark.parametrize("path", sorted(ACTIVITY_ENDPOINTS))
def test_no_activity_endpoint_claims_to_have_booked_anything(city, path):
    """Several went past inventing people and claimed a reservation: a rooftop tasting with a
    named sommelier, a guestlist spot, a sauna, a supper club. Nothing here can book."""
    client, people = city
    body = client.post(path, json={"city": "Lisbon", **ACTIVITY_ENDPOINTS[path]},
                       headers=people["ana"]["h"]).json()
    for claim in ("booked_venue", "reservation_status", "table_status", "rsvp_confirmed",
                  "salon_confirmed", "confirmed_members", "guestlist_confirmed"):
        assert claim not in body, f"{path} still reports {claim}"


@pytest.mark.parametrize("path", sorted(ACTIVITY_ENDPOINTS))
def test_no_activity_endpoint_invents_a_score(city, path):
    client, people = city
    body = client.post(path, json={"city": "Lisbon", **ACTIVITY_ENDPOINTS[path]},
                       headers=people["ana"]["h"]).json()
    assert "match_score" not in body and "compatibility_score" not in body, path


@pytest.mark.parametrize("path", sorted(ACTIVITY_ENDPOINTS))
def test_every_activity_endpoint_asks_for_a_city_rather_than_picking_one(city, path):
    """They all defaulted to Lisbon or Edinburgh in the handler signature."""
    client, people = city
    body = client.post(path, json=dict(ACTIVITY_ENDPOINTS[path]),
                       headers=people["ana"]["h"]).json()
    assert body["needs_city"] is True, path


# ---- a real match through one of them ----------------------------------------

def test_a_published_signal_is_found_through_a_category_endpoint(city):
    """The forty share one matcher, so proving one end to end proves the wiring."""
    client, people = city
    client.post("/v1/synergy/open-to", json={"city": "Lisbon", "activity": "bouldering"},
                headers=people["bruno"]["h"])
    body = client.post("/v1/hobbies/sports-outdoors",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is True
    assert body["people"][0]["handle"] == "bruno"


def test_each_endpoint_keeps_its_own_category_label(city):
    client, people = city
    labels = {}
    for path in ("/v1/nightlife/party-radar", "/v1/wellness/sauna-social",
                 "/v1/impact/eco-clean-crew"):
        labels[path] = client.post(path, json={"city": "Lisbon"},
                                   headers=people["ana"]["h"]).json()["category"]
    assert labels["/v1/nightlife/party-radar"] == "Nightlife"
    assert labels["/v1/wellness/sauna-social"] == "Wellness"
    assert labels["/v1/impact/eco-clean-crew"] == "Impact"


def test_the_endpoints_search_different_things(city):
    """A shared matcher must not become a shared *query* — somebody publishing a sauna plan
    should not turn up in a search for nightlife."""
    client, people = city
    client.post("/v1/synergy/open-to", json={"city": "Lisbon", "activity": "sauna"},
                headers=people["bruno"]["h"])
    sauna = client.post("/v1/wellness/sauna-social", json={"city": "Lisbon"},
                        headers=people["ana"]["h"]).json()
    night = client.post("/v1/nightlife/party-radar", json={"city": "Lisbon"},
                        headers=people["ana"]["h"]).json()
    assert sauna["matched"] is True and night["matched"] is False


# ---- swaps are mirrors --------------------------------------------------------

@pytest.mark.parametrize("path", sorted(SWAP_ENDPOINTS))
def test_a_swap_with_nobody_on_the_other_side_is_not_a_swap(city, path):
    """`swapped: True` and `swap_confirmed: True` came back for any pair of strings."""
    client, people = city
    body = client.post(path, json={"city": "Lisbon", **SWAP_ENDPOINTS[path]},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False
    assert "swapped" not in body and "swap_confirmed" not in body


def test_a_swap_matches_the_mirror(city):
    client, people = city
    client.post("/v1/synergy/open-to",
                json={"city": "Lisbon", "offers": "portuguese", "wants": "surfing"},
                headers=people["bruno"]["h"])
    body = client.post("/v1/economy/barter-swap",
                       json={"city": "Lisbon", "offering": "surfing",
                             "seeking": "portuguese"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is True
    assert body["people"][0]["handle"] == "bruno"


def test_a_swap_does_not_pair_two_people_who_need_the_same_thing(city):
    client, people = city
    client.post("/v1/synergy/open-to",
                json={"city": "Lisbon", "offers": "german", "wants": "portuguese"},
                headers=people["bruno"]["h"])
    body = client.post("/v1/economy/barter-swap",
                       json={"city": "Lisbon", "offering": "surfing",
                             "seeking": "portuguese"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False


def test_a_swap_needs_both_halves(city):
    client, people = city
    body = client.post("/v1/economy/barter-swap",
                       json={"city": "Lisbon", "offering": "surfing"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False
    assert "offering" in body["suggestion"]


# ---- the ones that map to real modules ---------------------------------------

def test_city_switch_shows_the_real_city_not_a_teleport(city):
    """"Teleported to Tokyo! 48 active nomads nearby" and a named hub, for any city."""
    client, people = city
    body = client.post("/v1/nomad/city-switch", json={"target_city": "Tokyo"},
                       headers=people["ana"]["h"]).json()
    assert body["label"] == "Tokyo"
    assert body["around"] == [] and body["empty"] is True
    assert "active_nomads_count" not in body


def test_the_global_bridge_is_two_real_rooms(city):
    client, people = city
    body = client.post("/v1/culture/global-bridge",
                       json={"city_a": "Lisbon", "city_b": "Tokyo"},
                       headers=people["ana"]["h"]).json()
    assert [c["label"] for c in body["cities"]] == ["Lisbon", "Tokyo"]
    assert "bridged" in body["note"]


def test_the_global_bridge_needs_two_cities(city):
    client, people = city
    assert client.post("/v1/culture/global-bridge", json={"city_a": "Lisbon"},
                       headers=people["ana"]["h"]).status_code == 400


def test_a_city_quest_draws_on_places_and_plans(city):
    client, people = city
    body = client.post("/v1/quests/city-discovery", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["places"] == [] and body["happening"] == []
    assert "QST-" not in str(body)              # it used to mint a quest id
    assert body["no_score"]


def test_the_sunset_ritual_writes_a_real_private_note(city):
    client, people = city
    first = client.post("/v1/rituals/sunset", json={"win_text": "finished the thing"},
                        headers=people["ana"]["h"]).json()
    assert first["logged"] is True and first["total"] == 1
    # And it is private: nobody else's count moves.
    other = client.post("/v1/rituals/sunset", json={},
                        headers=people["bruno"]["h"]).json()
    assert other["total"] == 0


def test_the_sunset_ritual_reports_no_streak_it_cannot_see(city):
    client, people = city
    body = client.post("/v1/rituals/sunset", json={"win_text": "x"},
                       headers=people["ana"]["h"]).json()
    assert "ritual_streak" not in body


def test_habit_stacking_creates_a_real_routine(city):
    """The anchor is literally the routine's trigger — which is what habit stacking is, and
    the tracker module has modelled it since Sprint 1 without this endpoint calling it."""
    client, people = city
    body = client.post("/v1/growth/habit-stacking",
                       json={"anchor_habit": "morning coffee",
                             "new_habit": "ten minutes of reading"},
                       headers=people["ana"]["h"]).json()
    assert body["routine_id"]
    assert body["no_adherence_score"]
    listed = client.get("/v1/routines", headers=people["ana"]["h"])
    if listed.status_code == 200:
        assert "ten minutes of reading" in listed.text


def test_habit_stacking_needs_both_halves(city):
    client, people = city
    assert client.post("/v1/growth/habit-stacking", json={"new_habit": "reading"},
                       headers=people["ana"]["h"]).status_code == 400


def test_the_travel_brief_composes_real_sources(city):
    client, people = city
    body = client.post("/v1/travel/curated-brief", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["whats_on"]["stops"] == []
    assert body["conditions"]["available"] is False    # no network in tests
    assert "curated_micro_escape" not in body
