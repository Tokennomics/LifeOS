"""Synergy matching — the eleven endpoints that used to answer with Elena R.

The point of these tests is not "a match is returned". It is the opposite: that **no match
is returned when there is nobody**, that the person returned is a real account that really
published something, and that the ways this could quietly go back to being a prop —
matching yourself, matching a muted person, matching an expired signal — all stay closed.

The single most important assertion in this file is the first one: an empty city returns
`matched: false`. That is the case the old implementation got wrong for every caller.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import synergy

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


def _open(client, who, activity="bouldering", city="Lisbon", **kw):
    return client.post("/v1/synergy/open-to",
                       json={"city": city, "activity": activity, **kw}, headers=who["h"])


# ---- the empty city, which is the normal case -------------------------------

def test_empty_city_matches_nobody(city):
    """The whole reason this module exists. Before, this returned Elena R. at 96%."""
    client, people = city
    res = client.post("/v1/synergy/sports-match", json={"city": "Lisbon",
                                                        "sport": "bouldering"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["matched"] is False
    assert body["people"] == []
    assert body["people_count"] == 0


def test_empty_city_says_what_would_fix_it(city):
    """"No results" with no next step is how an empty city stays empty."""
    client, people = city
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["suggestion"]
    assert "bouldering" in body["suggestion"]


def test_no_city_anywhere_asks_for_one_rather_than_inventing_one(city):
    client, people = city
    body = client.post("/v1/synergy/sports-match", json={"sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False
    assert body["needs_city"] is True


def test_searching_needs_a_session_like_the_rest_of_the_app(city):
    """Once accounts exist, an unauthenticated caller gets 401 everywhere — matching is not
    an exception. Worth pinning: the endpoint answers without a *body* city, and it would be
    easy to also let it answer without a caller, which would leak who is in a city to
    anybody with the URL."""
    client, _ = city
    res = client.post("/v1/synergy/sports-match",
                      json={"city": "Lisbon", "sport": "bouldering"})
    assert res.status_code == 401


# ---- a real match -----------------------------------------------------------

def test_a_real_person_who_published_is_found(city):
    client, people = city
    _open(client, people["bruno"], "bouldering", note="anyone for the crag at six")

    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is True
    assert [p["handle"] for p in body["people"]] == ["bruno"]
    assert body["people"][0]["account_id"] == people["bruno"]["id"]


def test_the_match_says_why_it_fired(city):
    """The replacement for `match_score: 97`. A number nobody can check is worse than a
    short list of the words that actually overlapped."""
    client, people = city
    _open(client, people["bruno"], "bouldering")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["people"][0]["shared_terms"] == ["bouldering"]


def test_no_invented_score_anywhere_in_the_response(city):
    client, people = city
    _open(client, people["bruno"], "bouldering")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert "match_score" not in body
    assert "partner_name" not in body
    assert "breakdown" not in body


def test_a_different_activity_does_not_match(city):
    client, people = city
    _open(client, people["bruno"], "surfing at carcavelos")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False


def test_a_different_city_does_not_match(city):
    client, people = city
    _open(client, people["bruno"], "bouldering", city="Porto")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False


def test_stemmed_forms_still_match(city):
    """`ski` and `skiing` are the same activity; a plain set intersection says they are not,
    and the two people who typed them differently never meet."""
    client, people = city
    _open(client, people["bruno"], "skiing")
    body = client.post("/v1/synergy/ski-match", json={"city": "Lisbon", "resort": "ski"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is True


def test_stopwords_alone_do_not_make_a_match(city):
    """"looking for people to surf with" and "looking for people to ski with" share four
    words and no activity."""
    client, people = city
    _open(client, people["bruno"], "looking for people to surf with")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon",
                             "sport": "looking for people to ski with"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False


# ---- who must never appear --------------------------------------------------

def test_you_never_match_yourself(city):
    client, people = city
    _open(client, people["ana"], "bouldering")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["people"] == []
    assert body["you_are_open"] is True


def test_being_the_only_one_open_changes_the_advice(city):
    client, people = city
    _open(client, people["ana"], "bouldering")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert "only one" in body["suggestion"]


def test_a_muted_person_does_not_reappear_as_a_match(city):
    """Somebody silenced in the room must not be handed back as a person to go meet."""
    client, people = city
    _open(client, people["mallory"], "bouldering")
    client.post("/v1/city/chat/mute", json={"target_id": people["mallory"]["id"]},
                headers=people["ana"]["h"])
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False


def test_an_expired_signal_does_not_match(graph):
    """A stale signal sends somebody to meet a person who went home two days ago."""
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="acc_b", handle="bruno",
                    hours=1)
    session = synergy._sys(graph)
    row = session.find_entities("content", {"type": synergy.RECORD}, limit=1)[0]
    gone = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=2)).isoformat()
    session.update_entity(row["id"], {"expires_at": gone}, source="test")

    assert synergy.find(graph, "Lisbon", "bouldering", viewer_id="acc_a")["matched"] is False


def test_a_withdrawn_signal_does_not_match(city):
    client, people = city
    _open(client, people["bruno"], "bouldering")
    client.request("DELETE", "/v1/synergy/open-to",
                   json={"city": "Lisbon", "activity": "bouldering"},
                   headers=people["bruno"]["h"])
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False


# ---- publishing a signal ----------------------------------------------------

def test_publishing_needs_a_session(city):
    client, _ = city
    res = client.post("/v1/synergy/open-to",
                      json={"city": "Lisbon", "activity": "bouldering"})
    assert res.status_code in (400, 401, 403)


def test_searching_does_not_publish_you(city):
    """Same rule as arrival: reading the room does not announce you."""
    client, people = city
    client.post("/v1/synergy/sports-match", json={"city": "Lisbon", "sport": "bouldering"},
                headers=people["ana"]["h"])
    mine = client.get("/v1/synergy/open-to", headers=people["ana"]["h"]).json()["signals"]
    assert mine == []


def test_reopening_replaces_rather_than_stacks(city):
    """Editing a note must not put you in the list twice."""
    client, people = city
    _open(client, people["bruno"], "bouldering", note="six at the crag")
    _open(client, people["bruno"], "bouldering", note="seven, actually")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["people_count"] == 1
    assert body["people"][0]["note"] == "seven, actually"


def test_you_can_see_what_you_are_publishing(city):
    client, people = city
    _open(client, people["ana"], "bouldering")
    _open(client, people["ana"], "coffee", city="Porto")
    mine = client.get("/v1/synergy/open-to", headers=people["ana"]["h"]).json()["signals"]
    assert {s["activity"] for s in mine} == {"bouldering", "coffee"}
    assert {s["city"] for s in mine} == {"lisbon", "porto"}


def test_closing_without_an_activity_closes_the_whole_city(city):
    client, people = city
    _open(client, people["ana"], "bouldering")
    _open(client, people["ana"], "coffee")
    _open(client, people["ana"], "coffee", city="Porto")
    client.request("DELETE", "/v1/synergy/open-to", json={"city": "Lisbon"},
                   headers=people["ana"]["h"])
    mine = client.get("/v1/synergy/open-to", headers=people["ana"]["h"]).json()["signals"]
    assert [s["city"] for s in mine] == ["porto"]


def test_hours_is_bounded(graph):
    with pytest.raises(synergy.SynergyError):
        synergy.open_to(graph, "Lisbon", "bouldering", account_id="a",
                        hours=synergy.MAX_HOURS + 1)


def test_zero_hours_is_refused_not_defaulted(graph):
    """`hours or DEFAULT_HOURS` would turn an explicit 0 into 4 — quietly publishing a
    signal the caller asked not to create. The same bug arrival had."""
    with pytest.raises(synergy.SynergyError):
        synergy.open_to(graph, "Lisbon", "bouldering", account_id="a", hours=0)


def test_a_signal_without_an_activity_is_refused(graph):
    with pytest.raises(synergy.SynergyError):
        synergy.open_to(graph, "Lisbon", "", account_id="a")


def test_publishing_needs_a_city(graph):
    with pytest.raises(synergy.SynergyError):
        synergy.open_to(graph, "", "bouldering", account_id="a")


def test_signals_expire_on_their_own(graph):
    """Availability is a statement about the next few hours, not a profile field."""
    out = synergy.open_to(graph, "Lisbon", "bouldering", account_id="a", hours=2)
    assert out["hours"] == 2
    row = synergy._sys(graph).get_entity(out["signal_id"])
    assert row["attrs"]["expires_at"] > row["attrs"]["created_at"]


# ---- the city is remembered -------------------------------------------------

def test_the_city_comes_from_your_arrival_when_you_do_not_repeat_it(city):
    """Somebody who has already said "I'm in Lisbon" should not be asked again — that
    friction is the difference between a signal published and one that never is."""
    client, people = city
    client.post("/v1/city/around", json={"city": "Lisbon", "note": "just landed"},
                headers=people["ana"]["h"])
    _open(client, people["bruno"], "bouldering")

    body = client.post("/v1/synergy/sports-match", json={"sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["city"] == "lisbon"
    assert body["matched"] is True


def test_an_explicit_city_beats_the_remembered_one(city):
    client, people = city
    client.post("/v1/city/around", json={"city": "Lisbon"}, headers=people["ana"]["h"])
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Porto", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["city"] == "porto"


def test_a_withdrawn_arrival_stops_being_the_default_city(graph):
    from modules.city import arrival
    arrival.announce(graph, "Lisbon", account_id="acc_a")
    assert synergy.city_for(graph, "acc_a") == "lisbon"
    arrival.withdraw(graph, "Lisbon", account_id="acc_a")
    assert synergy.city_for(graph, "acc_a") == ""


# ---- language swap: the mirror ---------------------------------------------

def test_language_swap_matches_the_mirror(city):
    client, people = city
    client.post("/v1/synergy/open-to",
                json={"city": "Lisbon", "offers": "Portuguese", "wants": "English"},
                headers=people["bruno"]["h"])
    body = client.post("/v1/synergy/language-swap",
                       json={"city": "Lisbon", "speak": "English",
                             "learn": "Portuguese"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is True
    assert body["people"][0]["handle"] == "bruno"


def test_language_swap_does_not_pair_two_learners(city):
    """Both want Portuguese. They share the word and can teach each other nothing — this is
    exactly what a same-terms matcher gets wrong."""
    client, people = city
    client.post("/v1/synergy/open-to",
                json={"city": "Lisbon", "offers": "German", "wants": "Portuguese"},
                headers=people["bruno"]["h"])
    body = client.post("/v1/synergy/language-swap",
                       json={"city": "Lisbon", "speak": "English",
                             "learn": "Portuguese"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False


def test_language_swap_needs_both_halves(city):
    client, people = city
    body = client.post("/v1/synergy/language-swap",
                       json={"city": "Lisbon", "speak": "English"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False
    assert "learn" in body["suggestion"]


def test_mentor_match_is_complementary_when_both_sides_are_given(city):
    client, people = city
    client.post("/v1/synergy/open-to",
                json={"city": "Lisbon", "offers": "product", "wants": "design"},
                headers=people["bruno"]["h"])
    body = client.post("/v1/synergy/mentor-match",
                       json={"city": "Lisbon", "offering": "design",
                             "seeking": "product"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is True
    assert body["category"] == "Mentorship"


# ---- meetups and events are part of the answer ------------------------------

def test_a_matching_meetup_counts_as_a_match(city):
    """Somebody who wants to climb should see the climbing meetup three people are already
    going to before being shown a stranger to message."""
    client, people = city
    soon = (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=5)).isoformat()
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Bouldering at Monsanto",
                      "starts_at": soon}, headers=people["bruno"]["h"])
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is True
    assert body["meetups"][0]["title"] == "Bouldering at Monsanto"


def test_an_unrelated_meetup_is_not_offered_as_a_match(city):
    client, people = city
    soon = (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=5)).isoformat()
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Wine tasting", "starts_at": soon},
                headers=people["bruno"]["h"])
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert body["matched"] is False
    assert body["meetups"] == []


def test_every_activity_endpoint_answers_honestly_when_empty(city):
    """All eleven ran off the same eleven literals. They now run off the same one matcher,
    so the empty case has to be uniform."""
    client, people = city
    calls = [
        ("/v1/synergy/instant-match", {"interest": "coffee"}),
        ("/v1/synergy/sports-match", {"sport": "bouldering"}),
        ("/v1/synergy/nomad-match", {"domain": "design"}),
        ("/v1/synergy/creative-match", {"genre": "acoustic"}),
        ("/v1/synergy/dining-match", {"cuisine": "ramen"}),
        ("/v1/synergy/ski-match", {"resort": "estrela"}),
        ("/v1/synergy/rave-match", {"subgenre": "techno"}),
        ("/v1/synergy/surf-match", {"spot": "carcavelos"}),
        ("/v1/synergy/mentor-match", {"domain": "product"}),
    ]
    for path, payload in calls:
        body = client.post(path, json={"city": "Lisbon", **payload},
                           headers=people["ana"]["h"]).json()
        assert body["matched"] is False, path
        assert body["people"] == [], path


def test_ski_and_surf_no_longer_assert_weather_nobody_measured(city):
    """`snow_depth_cm: 45` and a 2.2 m swell fired in July, in Lisbon, for everybody.

    Surf conditions are measured now (Open-Meteo marine, no key needed) but this test runs
    with no network, so what it pins is the other half: nothing is asserted when nothing was
    fetched, and snow depth stays absent because no piste provider exists at all.
    """
    client, people = city
    ski = client.post("/v1/synergy/ski-match", json={"city": "Lisbon"},
                      headers=people["ana"]["h"]).json()
    surf = client.post("/v1/synergy/surf-match", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert ski["conditions"]["available"] is False
    assert surf["conditions"]["available"] is False
    assert ski["snow_depth_cm"] is None
    assert "telemetry" not in surf


def test_a_caller_cannot_inject_conditions(city):
    """The old handler echoed `swell_m` straight back inside its telemetry block, so the
    caller's own number came back looking like a reading. Conditions come from the provider
    or they are unavailable."""
    client, people = city
    surf = client.post("/v1/synergy/surf-match",
                       json={"city": "Lisbon", "swell_m": 99.9},
                       headers=people["ana"]["h"]).json()
    assert "99.9" not in str(surf["conditions"])


def test_every_match_carries_the_safety_note(city):
    client, people = city
    _open(client, people["bruno"], "bouldering")
    body = client.post("/v1/synergy/sports-match",
                       json={"city": "Lisbon", "sport": "bouldering"},
                       headers=people["ana"]["h"]).json()
    assert "public" in body["safety_note"]


# ---- overlap ----------------------------------------------------------------

def test_overlap_is_empty_when_you_have_published_nothing(city):
    client, people = city
    body = client.get("/v1/synergy/overlap", headers=people["ana"]["h"]).json()
    assert body["overlaps"] == []
    assert body["open_signals"] == 0


def test_overlap_finds_the_person_who_wants_the_same_thing(city):
    client, people = city
    _open(client, people["ana"], "bouldering")
    _open(client, people["bruno"], "bouldering")
    body = client.get("/v1/synergy/overlap", headers=people["ana"]["h"]).json()
    assert len(body["overlaps"]) == 1
    assert body["overlaps"][0]["activity"] == "bouldering"
    assert body["overlaps"][0]["people"][0]["handle"] == "bruno"


def test_overlap_without_a_session_invents_nobody(city):
    """It used to return Alex and Elena to anyone who asked, signed in or not."""
    client, _ = city
    res = client.get("/v1/synergy/overlap")
    assert res.status_code == 401
    assert "Elena" not in res.text


def test_overlap_lists_no_friend_that_does_not_exist(city):
    """The old response named Alex and Elena, on a Friday, from a calendar the app has never
    had. Whatever comes back now has to be an account that published a signal."""
    client, people = city
    _open(client, people["ana"], "bouldering")
    body = client.get("/v1/synergy/overlap", headers=people["ana"]["h"]).json()
    assert body["overlaps"] == []
    assert body["open_signals"] == 1


# ---- tokenisation, directly -------------------------------------------------

def test_terms_drops_stopwords_and_punctuation():
    assert synergy.terms("Looking for people to surf with!") == {"surf"}


def test_terms_keeps_numbers_that_carry_meaning():
    assert "5a" in synergy.terms("bouldering 5a and up")


def test_shared_is_symmetric():
    assert synergy._shared("bouldering", "boulder") == synergy._shared("boulder",
                                                                       "bouldering")
