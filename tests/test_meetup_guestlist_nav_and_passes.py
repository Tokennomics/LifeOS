"""Four things hung off a meetup that never looked one up.

`/events/vip-guestlist` answered `granted: True` with `VIP-KARMA-98` for a venue defaulting
to "Miradouro Rooftop Bar". `/routing/group-nav` reported six members synced on a route and
a next turn 80m away. `/events/apple-wallet-pass` minted a pass for whatever `event_name`
was sent, with the same serial number every time. `/seeding/anchor-outings` reported three
weekly outings and a "Guaranteed Crew Host" in any city.

All four now start from a row: a meetup that exists, or nothing.
"""

import base64
import datetime
import json

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import anchors, guestlist, navigation, passes

PW = "correct-horse-battery"


def _soon(days: int = 2, hour: int = 19) -> str:
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


@pytest.fixture
def meetup(world):
    client, people = world
    made = client.post("/v1/city/meetups",
                       json={"city": "Lisbon", "title": "Sunset walk",
                             "place": "Miradouro da Graca", "starts_at": _soon()},
                       headers=people["ana"]["h"])
    assert made.status_code == 200, made.text
    return made.json()["meetup_id"]


# ---- the modules -------------------------------------------------------------

def test_a_guest_list_needs_a_meetup_that_exists(graph):
    with pytest.raises(guestlist.GuestlistError):
        guestlist.listing(graph, "", viewer_id="acct-1")
    with pytest.raises(guestlist.GuestlistError):
        guestlist.listing(graph, "not-an-id", viewer_id="acct-1")


def test_navigation_needs_a_meetup_that_exists(graph):
    with pytest.raises(navigation.NavigationError):
        navigation.where(graph, "")
    with pytest.raises(navigation.NavigationError):
        navigation.where(graph, "not-an-id")


def test_a_pass_for_an_id_that_names_nothing_is_not_found(graph):
    with pytest.raises(passes.UnknownEvent):
        passes.wallet_pass(graph, "not-an-id")
    with pytest.raises(passes.PassError):
        passes.wallet_pass(graph, "")


def test_anchors_refuse_to_invent_the_outings(graph):
    with pytest.raises(anchors.AnchorError):
        anchors.create(graph, "Lisbon", outings=[], account_id="acct-1")
    with pytest.raises(anchors.AnchorError):
        anchors.create(graph, "", outings=[{"title": "Surf", "starts_at": _soon()}],
                       account_id="acct-1")
    with pytest.raises(anchors.AnchorError):
        anchors.create(graph, "Lisbon", outings=[{"title": "Surf"}],
                       account_id="acct-1")


def test_anchors_write_one_meetup_per_week_and_report_what_was_written(graph):
    from modules.city import meetups
    out = anchors.create(graph, "Lisbon", weeks=3, account_id="acct-1", handle="ana",
                         outings=[{"title": "Dawn swim", "starts_at": _soon(),
                                   "place": "The beach"}])
    assert out["count"] == 3
    assert [entry["week"] for entry in out["created"]] == [1, 2, 3]
    listed = meetups.listing(graph, "Lisbon", viewer_id="acct-1")["meetups"]
    assert len(listed) == 3
    assert {row["title"] for row in listed} == {"Dawn swim"}
    # The person who ran it is the organiser of each and is counted as going, which is the
    # honest version of the "Guaranteed Crew Host" the prop promised.
    assert all(row["organiser_id"] == "acct-1" and row["going_count"] == 1
               for row in listed)
    assert "guarantee" not in str(out["created"]).lower()


def test_an_outing_that_cannot_be_created_is_reported_not_silently_dropped(graph):
    long_ago = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(days=5)).isoformat()
    out = anchors.create(graph, "Lisbon", account_id="acct-1",
                         outings=[{"title": "Dawn swim", "starts_at": _soon()},
                                  {"title": "Old one", "starts_at": long_ago}])
    assert out["count"] == 1
    assert [row["title"] for row in out["skipped"]] == ["Old one"]
    assert out["skipped"][0]["reason"]


# ---- over HTTP ---------------------------------------------------------------

def test_the_guest_list_is_the_organisers_and_grants_nothing(world, meetup):
    client, people = world
    added = client.post("/v1/events/vip-guestlist",
                        json={"meetup_id": meetup, "guests": ["bruno"]},
                        headers=people["ana"]["h"])
    assert added.status_code == 200
    assert added.json()["guest_count"] == 1 and added.json()["granted"] is False

    seen = client.post("/v1/events/vip-guestlist", json={"meetup_id": meetup},
                       headers=people["bruno"]["h"])
    assert seen.status_code == 200
    assert [row["handle"] for row in seen.json()["guests"]] == ["bruno"]
    assert seen.json()["you_are_on_it"] is True
    for invented in ("vip", "fast", "pass_code", "karma", "access_tier"):
        assert invented not in seen.text.lower()


def test_only_the_organiser_writes_the_list(world, meetup):
    client, people = world
    res = client.post("/v1/events/vip-guestlist",
                      json={"meetup_id": meetup, "guests": ["ana"]},
                      headers=people["bruno"]["h"])
    assert res.status_code == 400


def test_a_guest_who_is_nobody_here_is_refused(world, meetup):
    client, people = world
    res = client.post("/v1/events/vip-guestlist",
                      json={"meetup_id": meetup, "guests": ["nobody"]},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "nobody here goes by" in res.text


def test_a_guest_list_without_a_meetup_is_400_not_a_default_venue(world):
    client, people = world
    res = client.post("/v1/events/vip-guestlist", json={}, headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "miradouro rooftop bar" not in res.text.lower()


def test_group_nav_returns_the_place_and_refuses_to_route(world, meetup):
    client, people = world
    client.post("/v1/city/meetups/join", json={"meetup_id": meetup},
                headers=people["bruno"]["h"])

    res = client.post("/v1/routing/group-nav", json={"meetup_id": meetup},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["routing"] is False and body["coordinates"] is False
    assert body["place"] == "Miradouro da Graca"
    assert body["going_count"] == 2
    assert {row["handle"] for row in body["going"]} == {"ana", "bruno"}
    for invented in ("next_turn", "waypoints_count", "live_sync_interval",
                     "navigation_active", "group_members_on_route"):
        assert invented not in res.text


def test_group_nav_without_a_meetup_is_400(world):
    client, people = world
    res = client.post("/v1/routing/group-nav", json={"route_name": "Sunset Walk"},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "alfama" not in res.text.lower()


def test_group_nav_reports_who_announced_they_are_in_the_city(world, meetup):
    client, people = world
    client.post("/v1/city/around", json={"city": "Lisbon"}, headers=people["ana"]["h"])
    res = client.post("/v1/routing/group-nav", json={"meetup_id": meetup},
                      headers=people["ana"]["h"])
    ana = [row for row in res.json()["going"] if row["handle"] == "ana"][0]
    assert ana["announced_in_city"] is True


def test_a_wallet_pass_is_built_from_the_meetups_own_fields(world, meetup):
    client, people = world
    res = client.post("/v1/events/apple-wallet-pass", json={"meetup_id": meetup},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["pkpass_url"].startswith("data:application/vnd.apple.pkpass;base64,")
    payload = json.loads(base64.b64decode(
        body["pkpass_url"].split("base64,")[1]).decode("utf-8"))
    assert payload["description"] == "Sunset walk"
    assert payload["serialNumber"] == meetup
    assert body["signed"] is False and body["grants_entry"] is False
    assert "connectos.app" not in res.text
    for invented in ("VIP-KARMA-98", "FAST-PASS", "wallet_type"):
        assert invented not in res.text


def test_a_pass_for_an_event_that_does_not_exist_is_a_404(world):
    client, people = world
    res = client.post("/v1/events/apple-wallet-pass",
                      json={"event_name": "Rooftop Party"}, headers=people["ana"]["h"])
    assert res.status_code == 400        # nothing to look up at all
    unknown = client.post("/v1/events/apple-wallet-pass",
                          json={"meetup_id": "no-such-id"}, headers=people["ana"]["h"])
    assert unknown.status_code == 404
    assert "pkpass" not in unknown.text


def test_two_passes_do_not_share_a_serial_number(world, meetup):
    client, people = world
    second = client.post("/v1/city/meetups",
                         json={"city": "Lisbon", "title": "Morning swim",
                               "starts_at": _soon(days=3)},
                         headers=people["ana"]["h"]).json()["meetup_id"]

    def serial(meetup_id):
        body = client.post("/v1/events/apple-wallet-pass", json={"meetup_id": meetup_id},
                           headers=people["ana"]["h"]).json()
        return json.loads(base64.b64decode(
            body["pkpass_url"].split("base64,")[1]).decode("utf-8"))["serialNumber"]

    assert serial(meetup) != serial(second)


def test_anchor_outings_are_operator_only_and_create_real_meetups(world, monkeypatch):
    client, people = world
    denied = client.post("/v1/seeding/anchor-outings",
                         json={"city": "Lisbon",
                               "outings": [{"title": "Dawn swim", "starts_at": _soon()}]},
                         headers=people["ana"]["h"])
    assert denied.status_code == 403

    monkeypatch.setenv("LIFEOS_MODERATOR_ACCOUNTS", people["ana"]["id"])
    made = client.post("/v1/seeding/anchor-outings",
                       json={"city": "Lisbon", "weeks": 2,
                             "outings": [{"title": "Dawn swim", "starts_at": _soon(),
                                          "place": "The beach"}]},
                       headers=people["ana"]["h"])
    assert made.status_code == 200
    body = made.json()
    assert body["count"] == 2
    # Searched on the created rows and the keys, not the whole body: the honest copy names
    # what it disclaims ("Nobody is guaranteed to be there"), so a whole-text search for
    # "guaranteed" would fail on the disclaimer that replaced the claim.
    for invented in ("spots_reserved", "anchors_active", "weekly_anchors",
                     "steward_guarantee"):
        assert invented not in body
    assert "carcavelos" not in str(body["created"]).lower()
    assert "guarantee" not in str(body["created"]).lower()

    board = client.get("/v1/city/meetups?city=Lisbon", headers=people["bruno"]["h"])
    titles = [row["title"] for row in board.json()["meetups"]]
    assert titles.count("Dawn swim") == 2


def test_anchor_outings_with_no_outings_creates_nothing(world, monkeypatch):
    client, people = world
    monkeypatch.setenv("LIFEOS_MODERATOR_ACCOUNTS", people["ana"]["id"])
    res = client.post("/v1/seeding/anchor-outings", json={"city": "Lisbon"},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    for invented in ("surf", "sauna", "farmers market"):
        assert invented not in res.text.lower()
