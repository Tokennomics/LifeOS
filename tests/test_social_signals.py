"""Kudos, reviews, moments, check-ins — and SafeWalk, which is the serious one.

Four endpoints stored nothing and reported constants: a "kudos karma" total, a kindness
streak, three reviews signed by people who do not exist, a photo moment with a view count.
Those are ordinary props and these tests are ordinary.

SafeWalk is not ordinary. `/safety/escort` returned `escort_code: "SAFE-8921"` — the same
code for every walk in the world — and told the caller their crew had been notified.
`/safety/squad-beacon` broadcast a location. `/safety/emergency-sos` reported
`recipients_notified: 4`. Nothing was sent anywhere. Every other prop in this repo wasted
somebody's time; this one changes how a person behaves on a walk home, because somebody who
believes their crew is watching takes a route somebody who knows nobody is would not.

So the assertions that matter most here are the negative ones: that nothing claims delivery,
that no location is stored, and that a watcher who was not named cannot see the walk.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.safety import watch
from modules.social import signals

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def city(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno", "carla"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


# ---- kudos -------------------------------------------------------------------

def test_a_kudos_is_stored_and_the_recipient_can_read_it(city):
    """It returned a running "kudos karma" that was the same number for everyone, and wrote
    nothing at all."""
    client, people = city
    sent = client.post("/v1/kudos/send",
                       json={"to_account": people["bruno"]["id"],
                             "note": "you carried the whole night"},
                       headers=people["ana"]["h"]).json()
    assert sent["sent"] is True
    got = client.get("/v1/kudos", headers=people["bruno"]["h"]).json()
    assert got["kudos"][0]["note"] == "you carried the whole night"
    assert got["kudos"][0]["from_handle"] == "ana"


def test_the_subject_of_a_note_can_always_see_it(city):
    """The design decision worth pinning: a note about a person that the person cannot read
    is not a kudos, it is a file on them."""
    client, people = city
    client.post("/v1/kudos/send",
                json={"to_account": people["bruno"]["id"], "note": "thanks"},
                headers=people["ana"]["h"])
    assert client.get("/v1/kudos", headers=people["bruno"]["h"]).json()["total"] == 1


def test_a_third_party_sees_nothing(city):
    client, people = city
    client.post("/v1/kudos/send",
                json={"to_account": people["bruno"]["id"], "note": "thanks"},
                headers=people["ana"]["h"])
    assert client.get("/v1/kudos", headers=people["carla"]["h"]).json()["kudos"] == []


def test_kudos_carry_no_score(city):
    client, people = city
    body = client.post("/v1/kudos/send",
                       json={"to_account": people["bruno"]["id"], "note": "thanks"},
                       headers=people["ana"]["h"]).json()
    assert body["no_score"]
    assert "karma" not in str(body).lower() or "No karma" in body["no_score"]


def test_you_cannot_send_yourself_kudos(graph):
    with pytest.raises(signals.SignalError):
        signals.send_kudos(graph, "a", "nice one", account_id="a")


def test_a_kudos_needs_a_recipient_and_a_reason(graph):
    with pytest.raises(signals.SignalError):
        signals.send_kudos(graph, "", "thanks", account_id="a")
    with pytest.raises(signals.SignalError):
        signals.send_kudos(graph, "b", "  ", account_id="a")


def test_kindness_is_the_same_object_with_a_different_kind(city):
    client, people = city
    client.post("/v1/social/kindness",
                json={"to_account": people["bruno"]["id"], "note": "you waited with me"},
                headers=people["ana"]["h"])
    got = client.get("/v1/kudos", headers=people["bruno"]["h"]).json()
    assert got["kudos"][0]["kind"] == "kindness"


def test_kindness_reports_no_streak(city):
    client, people = city
    body = client.post("/v1/social/kindness",
                       json={"to_account": people["bruno"]["id"], "note": "x"},
                       headers=people["ana"]["h"]).json()
    assert "kindness_streak" not in body


# ---- reviews -----------------------------------------------------------------

def test_a_review_is_about_a_place(city):
    client, people = city
    client.post("/v1/feed/reviews",
                json={"city": "Lisbon", "place": "The corner bar",
                      "review": "quiet on a Tuesday", "rating": 4},
                headers=people["ana"]["h"])
    got = client.get("/v1/feed/reviews?city=Lisbon", headers=people["bruno"]["h"]).json()
    assert got["reviews"][0]["place"] == "The corner bar"
    assert got["reviews"][0]["rating"] == 4


def test_reviews_start_empty_rather_than_seeded_with_strangers(city):
    """It returned three reviews of Lisbon venues signed by people who do not exist."""
    client, people = city
    got = client.get("/v1/feed/reviews?city=Lisbon", headers=people["ana"]["h"]).json()
    assert got["reviews"] == [] and got["empty"] is True
    assert "first" in got["suggestion"]


def test_a_review_needs_a_place_and_something_to_say(graph):
    with pytest.raises(signals.SignalError):
        signals.write_review(graph, "Lisbon", "", "great", account_id="a")
    with pytest.raises(signals.SignalError):
        signals.write_review(graph, "Lisbon", "The bar", "   ", account_id="a")


def test_a_rating_is_bounded(graph):
    with pytest.raises(signals.SignalError):
        signals.write_review(graph, "Lisbon", "The bar", "fine", account_id="a", rating=11)


def test_a_rating_is_optional(graph):
    out = signals.write_review(graph, "Lisbon", "The bar", "fine", account_id="a")
    assert out["written"] is True
    assert signals.reviews(graph, city="Lisbon")["reviews"][0]["rating"] is None


def test_reviews_are_scoped_to_their_city(graph):
    signals.write_review(graph, "Lisbon", "The bar", "fine", account_id="a")
    assert signals.reviews(graph, city="Porto")["reviews"] == []


# ---- moments -----------------------------------------------------------------

def test_a_moment_is_public_in_its_city(city):
    client, people = city
    client.post("/v1/moments/flash", json={"city": "Lisbon", "caption": "the light tonight"},
                headers=people["ana"]["h"])
    got = client.get("/v1/moments?city=Lisbon", headers=people["bruno"]["h"]).json()
    assert got["moments"][0]["caption"] == "the light tonight"


def test_a_moment_counts_no_views(city):
    client, people = city
    body = client.post("/v1/moments/flash", json={"city": "Lisbon", "caption": "x"},
                       headers=people["ana"]["h"]).json()
    assert body["no_views"]
    assert "view_count" not in body


def test_a_moment_expires(graph):
    signals.post_moment(graph, "Lisbon", "tonight", account_id="a")
    session = signals._sys(graph)
    row = session.find_entities("content", {"type": signals.MOMENT}, limit=1)[0]
    gone = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1)).isoformat()
    session.update_entity(row["id"], {"expires_at": gone}, source="test")
    assert signals.moments(graph, "Lisbon")["moments"] == []


def test_a_muted_person_does_not_appear_in_moments(city):
    client, people = city
    client.post("/v1/moments/flash", json={"city": "Lisbon", "caption": "hi"},
                headers=people["carla"]["h"])
    client.post("/v1/city/chat/mute", json={"target_id": people["carla"]["id"]},
                headers=people["ana"]["h"])
    got = client.get("/v1/moments?city=Lisbon", headers=people["ana"]["h"]).json()
    assert got["moments"] == []


# ---- check-ins ---------------------------------------------------------------

def test_a_check_in_is_recorded_and_is_yours(city):
    client, people = city
    client.post("/v1/events/qr-checkin", json={"place": "The viewpoint", "city": "Lisbon"},
                headers=people["ana"]["h"])
    mine = client.get("/v1/checkins", headers=people["ana"]["h"]).json()
    assert mine["check_ins"][0]["place"] == "The viewpoint"
    assert client.get("/v1/checkins", headers=people["bruno"]["h"]).json()["total"] == 0


def test_a_check_in_mints_nothing(city):
    """`/gamification/mint-presence` minted a "POP-" token: nobody issued it, it sits on no
    chain, it is signed by nothing and it verifies nothing."""
    client, people = city
    body = client.post("/v1/gamification/mint-presence", json={"event_name": "Rooftop"},
                       headers=people["ana"]["h"]).json()
    assert body["minted"] is False
    assert "POP-" not in str(body)


def test_a_check_in_awards_nothing(city):
    client, people = city
    body = client.post("/v1/events/qr-checkin", json={"place": "The bar"},
                       headers=people["ana"]["h"]).json()
    assert "bonus_karma" not in body


def test_a_check_in_makes_outings_attended_true(city):
    """The number `standing()` reports has to come from something. This is that something —
    an RSVP is an intention, a check-in is the evening."""
    client, people = city
    before = client.get("/v1/trust/karma-score", headers=people["ana"]["h"]).json()
    assert before["outings_attended"] == 0 and before["empty"] is True
    client.post("/v1/events/qr-checkin", json={"place": "The viewpoint"},
                headers=people["ana"]["h"])
    after = client.get("/v1/trust/karma-score", headers=people["ana"]["h"]).json()
    assert after["outings_attended"] == 1 and after["empty"] is False


def test_a_check_in_needs_somewhere(graph):
    with pytest.raises(signals.SignalError):
        signals.check_in(graph, account_id="a")


# ---- SafeWalk: the serious one ----------------------------------------------

def test_a_walk_is_recorded_with_a_real_deadline(city):
    client, people = city
    body = client.post("/v1/safety/escort",
                       json={"destination": "home", "eta_mins": 25,
                             "watchers": [people["bruno"]["id"]]},
                       headers=people["ana"]["h"]).json()
    assert body["watching"] is True and body["eta_minutes"] == 25
    assert body["can_see_it"] == 1


def test_nothing_claims_to_have_notified_anybody(city):
    """"Crew notified & ETA timer set" was the sentence. No message left the building."""
    client, people = city
    body = client.post("/v1/safety/escort",
                       json={"destination": "home", "watchers": [people["bruno"]["id"]]},
                       headers=people["ana"]["h"]).json()
    assert body["push_delivered"] is False
    assert "nobody has been messaged" in body["delivery_note"].lower()
    assert "recipients_notified" not in body


def test_the_escort_code_is_gone(city):
    """`SAFE-8921` was the same code for every walk in the world, so it verified nothing."""
    client, people = city
    text = client.post("/v1/safety/escort", json={"destination": "home"},
                       headers=people["ana"]["h"]).text
    assert "SAFE-8921" not in text and "escort_code" not in text


def test_naming_no_watchers_says_so_plainly(city):
    """The worst outcome is somebody walking home believing they are watched when the list
    is empty."""
    client, people = city
    body = client.post("/v1/safety/escort", json={"destination": "home"},
                       headers=people["ana"]["h"]).json()
    assert body["can_see_it"] == 0
    assert "nobody can see this" in body["delivery_note"].lower()


def test_a_named_watcher_can_see_the_walk(city):
    client, people = city
    client.post("/v1/safety/escort",
                json={"destination": "home", "watchers": [people["bruno"]["id"]]},
                headers=people["ana"]["h"])
    seen = client.get("/v1/safety/watching", headers=people["bruno"]["h"]).json()
    assert seen["walks"][0]["destination"] == "home"
    assert seen["walks"][0]["handle"] == "ana"


def test_somebody_not_named_cannot(city):
    client, people = city
    client.post("/v1/safety/escort",
                json={"destination": "home", "watchers": [people["bruno"]["id"]]},
                headers=people["ana"]["h"])
    assert client.get("/v1/safety/watching",
                      headers=people["carla"]["h"]).json()["walks"] == []


def test_an_overdue_walk_is_flagged_and_sorted_first(graph):
    watch.start(graph, "home", account_id="ana", handle="ana", eta_minutes=30,
                watchers=["bruno"])
    session = watch._sys(graph)
    row = session.find_entities("content", {"type": watch.RECORD}, limit=1)[0]
    past = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=20)).isoformat()
    session.update_entity(row["id"], {"due_at": past}, source="test")

    seen = watch.watching(graph, account_id="bruno")
    assert seen["overdue_count"] == 1
    assert seen["walks"][0]["overdue"] is True
    assert seen["walks"][0]["overdue_minutes"] >= 19


def test_arriving_clears_the_watch(city):
    client, people = city
    client.post("/v1/safety/escort",
                json={"destination": "home", "watchers": [people["bruno"]["id"]]},
                headers=people["ana"]["h"])
    client.post("/v1/safety/escort/arrived", json={}, headers=people["ana"]["h"])
    assert client.get("/v1/safety/watching",
                      headers=people["bruno"]["h"]).json()["walks"] == []


def test_cancelling_clears_it_too(city):
    client, people = city
    client.post("/v1/safety/escort",
                json={"destination": "home", "watchers": [people["bruno"]["id"]]},
                headers=people["ana"]["h"])
    client.request("DELETE", "/v1/safety/escort", headers=people["ana"]["h"])
    assert client.get("/v1/safety/escort", headers=people["ana"]["h"]).json()["walks"] == []


def test_starting_a_second_walk_replaces_the_first(graph):
    """Two overlapping ETAs is how a watcher stops trusting the list."""
    watch.start(graph, "home", account_id="ana", watchers=["bruno"])
    watch.start(graph, "the station", account_id="ana", watchers=["bruno"])
    seen = watch.watching(graph, account_id="bruno")
    assert len(seen["walks"]) == 1
    assert seen["walks"][0]["destination"] == "the station"


def test_no_coordinate_is_ever_stored(graph):
    """There is no background location in a PWA, and a safety feature that implies live
    tracking is worse than one that says plainly what it does."""
    watch.start(graph, "home", account_id="ana", watchers=["bruno"])
    row = watch._sys(graph).find_entities("content", {"type": watch.RECORD}, limit=1)[0]
    assert "lat" not in row["attrs"] and "lon" not in row["attrs"]


def test_the_sos_is_the_same_object_and_the_same_honesty(city):
    client, people = city
    body = client.post("/v1/safety/emergency-sos",
                       json={"location": "the corner", "watchers": [people["bruno"]["id"]]},
                       headers=people["ana"]["h"]).json()
    assert body["severity"] == "sos"
    assert body["push_delivered"] is False
    assert "SOS-9911-GPS" not in str(body)


def test_every_walk_carries_the_disclaimer(city):
    client, people = city
    body = client.post("/v1/safety/escort", json={"destination": "home"},
                       headers=people["ana"]["h"]).json()
    assert "cannot call anyone" in body["disclaimer"]
    assert "emergency number" in body["disclaimer"]


def test_the_community_grid_is_the_people_who_named_you(city):
    """It was a grid of invented safe houses and volunteer counts."""
    client, people = city
    client.post("/v1/safety/escort",
                json={"destination": "home", "watchers": [people["bruno"]["id"]]},
                headers=people["ana"]["h"])
    grid = client.get("/v1/safety/community-grid", headers=people["bruno"]["h"]).json()
    assert grid["walks"][0]["handle"] == "ana"


def test_an_eta_is_bounded(graph):
    with pytest.raises(watch.WatchError):
        watch.start(graph, "home", account_id="a", eta_minutes=watch.MAX_MINUTES + 1)


def test_a_zero_eta_is_refused_not_defaulted(graph):
    with pytest.raises(watch.WatchError):
        watch.start(graph, "home", account_id="a", eta_minutes=0)


def test_a_walk_needs_a_destination(graph):
    with pytest.raises(watch.WatchError):
        watch.start(graph, "  ", account_id="a")


def test_a_walk_needs_a_session(graph):
    with pytest.raises(watch.WatchError):
        watch.start(graph, "home", account_id="")


# ---- a page-load 422 that hid an empty feature ------------------------------

def test_venues_explore_does_not_422_without_a_city(city):
    """`city` was a required query parameter and the PWA called this with none on every page
    load. The client `.catch()`-ed it, so Explore was permanently empty and never *looked*
    broken — found by watching the network tab during a browser walk, not by any test."""
    client, people = city
    res = client.get("/v1/venues/explore", headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.json()["needs_city"] is True


def test_venues_explore_uses_the_city_you_announced(city):
    client, people = city
    client.post("/v1/city/around", json={"city": "Lisbon"}, headers=people["ana"]["h"])
    res = client.get("/v1/venues/explore", headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.json()["city"] == "lisbon"


def test_an_explicit_city_still_works(city):
    client, people = city
    res = client.get("/v1/venues/explore?city=Porto", headers=people["ana"]["h"])
    assert res.status_code == 200 and res.json()["city"] == "Porto"


def test_explore_returns_the_shape_the_client_actually_reads(city):
    """The module returns a bare list; the PWA reads `res.venues`. Two silent mismatches
    stacked on one feature — the 422 and the shape — and neither was visible from Python."""
    client, people = city
    body = client.get("/v1/venues/explore?city=Porto", headers=people["ana"]["h"]).json()
    assert isinstance(body["venues"], list)


def test_single_user_owner_mode_can_still_write(cfg):
    """The NucBox shape: no accounts, an owner key, no `account_id` anywhere.

    `_signal_caller` returned "" there, which turned every endpoint in this file into a 400
    for the one deployment shape the repo started with. The config owner is the actor.
    """
    client = TestClient(create_app(cfg))
    assert client.post("/v1/safety/escort",
                       json={"destination": "home", "eta_mins": 20}).status_code == 200
    assert client.post("/v1/events/qr-checkin",
                       json={"place": "the bar"}).status_code == 200
    assert client.post("/v1/moments/flash",
                       json={"city": "Lisbon", "caption": "hi"}).status_code == 200
