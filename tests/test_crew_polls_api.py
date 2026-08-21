"""Polls, beacons and the plus-one pass over HTTP.

The guest pass is the one worth reading closely. It returned
`https://lifeos.app/#join-crew?crew_id=<id>&token=plus_one_<the same id>` — a token derived
from the crew id, stored nowhere, granting nothing, pointing at a domain this deployment
does not serve. Anyone who saw a crew id could write a "pass" for it themselves; it just
happened not to matter, because redeeming it did nothing either.
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
def crew(cfg):
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


def _open_poll(client, headers, crew_id):
    return client.post("/v1/crews/polls",
                       json={"crew_id": crew_id, "question": "thursday?",
                             "options": ["bouldering", "dinner"]},
                       headers=headers).json()


def test_a_poll_can_be_opened_voted_in_and_read(crew):
    client, people, crew_id = crew
    opened = _open_poll(client, people["ana"]["h"], crew_id)
    assert opened["opened"] is True

    voted = client.post("/v1/crews/polls/vote",
                        json={"poll_id": opened["poll_id"], "option": "dinner"},
                        headers=people["bruno"]["h"]).json()
    assert voted["total_votes"] == 1
    assert voted["leading"] == ["dinner"]

    res = client.get(f"/v1/crews/{crew_id}/polls", headers=people["ana"]["h"])
    assert res.status_code == 200, res.text
    listed = res.json()
    assert listed["polls"][0]["total_votes"] == 1
    assert listed["polls"][0]["you_voted"] is False


def test_a_vote_for_an_option_that_is_not_offered_is_refused(crew):
    client, people, crew_id = crew
    opened = _open_poll(client, people["ana"]["h"], crew_id)
    res = client.post("/v1/crews/polls/vote",
                      json={"poll_id": opened["poll_id"], "option": "Bouldering & Drinks"},
                      headers=people["bruno"]["h"])
    assert res.status_code == 400


def test_a_non_member_sees_no_poll(crew):
    client, people, crew_id = crew
    opened = _open_poll(client, people["ana"]["h"], crew_id)
    assert client.get(f"/v1/crews/polls/{opened['poll_id']}",
                      headers=people["carla"]["h"]).status_code == 400
    assert client.get(f"/v1/crews/{crew_id}/polls",
                      headers=people["carla"]["h"]).status_code == 400


def test_a_beacon_says_plainly_that_nobody_was_told(crew):
    client, people, crew_id = crew
    out = client.post("/v1/crews/beacon",
                      json={"crew_id": crew_id, "activity": "coffee then bouldering",
                            "minutes": 30},
                      headers=people["ana"]["h"]).json()
    assert out["push_delivered"] is False
    assert out["can_see_it"] == 1
    assert "broadcast" not in str(out).lower()


def test_a_beacon_can_be_answered(crew):
    client, people, crew_id = crew
    raised = client.post("/v1/crews/beacon",
                         json={"crew_id": crew_id, "activity": "coffee"},
                         headers=people["ana"]["h"]).json()
    joined = client.post("/v1/crews/beacon/join",
                         json={"beacon_id": raised["beacon_id"]},
                         headers=people["bruno"]["h"]).json()
    assert joined["coming"] == ["bruno"]

    res = client.get(f"/v1/crews/{crew_id}/beacons", headers=people["ana"]["h"])
    assert res.status_code == 200, res.text
    live = res.json()
    assert live["beacons"][0]["coming_count"] == 1
    assert live["push_delivered"] is False


def test_a_beacon_with_no_activity_is_refused(crew):
    client, people, crew_id = crew
    res = client.post("/v1/crews/beacon", json={"crew_id": crew_id},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "Bouldering" not in res.text


# ---- the plus-one pass -------------------------------------------------------

def test_a_guest_pass_is_a_real_single_use_invite(crew):
    client, people, crew_id = crew
    out = client.post(f"/v1/crews/{crew_id}/guest-pass", json={},
                      headers=people["ana"]["h"]).json()
    assert out["plus_one"] is True
    assert out["max_uses"] == 1
    assert out["invite_path"] == f"/invite/{out['token']}"

    # It actually admits somebody, which the old one never did.
    joined = client.post("/v1/crews/invite-link/redeem", json={"token": out["token"]},
                         headers=people["carla"]["h"])
    assert joined.status_code == 200

    # And exactly one somebody.
    again = client.post("/v1/crews/invite-link/redeem", json={"token": out["token"]},
                        headers=people["bruno"]["h"])
    assert again.status_code == 400


def test_the_pass_token_is_not_derived_from_the_crew_id(crew):
    """The old token was `plus_one_<crew_id>`, so seeing a crew id was the same as holding a
    pass for it."""
    client, people, crew_id = crew
    out = client.post(f"/v1/crews/{crew_id}/guest-pass", json={},
                      headers=people["ana"]["h"]).json()
    assert crew_id not in out["token"]
    assert "plus_one_" not in out["token"]
    assert len(out["token"]) >= 40

    forged = client.post("/v1/crews/invite-link/redeem",
                         json={"token": f"plus_one_{crew_id}"},
                         headers=people["carla"]["h"])
    assert forged.status_code == 400


def test_the_pass_points_at_this_deployment_not_a_hardcoded_domain(crew):
    client, people, crew_id = crew
    out = client.post(f"/v1/crews/{crew_id}/guest-pass", json={},
                      headers=people["ana"]["h"]).json()
    assert "lifeos.app" not in str(out)
    assert out["invite_path"].startswith("/invite/")


def test_only_an_admin_mints_a_pass(crew):
    client, people, crew_id = crew
    res = client.post(f"/v1/crews/{crew_id}/guest-pass", json={},
                      headers=people["bruno"]["h"])
    assert res.status_code == 400


def test_a_member_can_see_a_crew_they_did_not_create(crew):
    """`GET /crews` browses your own graph, so a crew you *joined* was invisible to you —
    it belongs to whoever created it and membership lives in the ACL. `crews.my_crews` was
    written for exactly this and was wired to no endpoint, which made every per-crew
    surface unreachable for anybody but the creator.
    """
    client, people, crew_id = crew
    own = client.get("/v1/crews", headers=people["bruno"]["h"]).json()["crews"]
    assert [c for c in own if c["id"] == crew_id] == []

    mine = client.get("/v1/crews/mine", headers=people["bruno"]["h"]).json()["crews"]
    assert [c["id"] for c in mine] == [crew_id]

    # And a stranger is in neither.
    assert client.get("/v1/crews/mine",
                      headers=people["carla"]["h"]).json()["crews"] == []


def test_no_route_is_shadowed_by_an_earlier_wildcard(cfg):
    """`GET /crews/polls` was swallowed by `GET /crews/{crew_id}`, declared above it — the
    word "polls" arrived as a crew id and the caller got "unknown crew" from a route that
    looked correct in the source. Routes are matched in declaration order, so a literal
    segment must come before the parameter that can absorb it.

    With ~480 routes in one file that is a mistake nobody spots by reading, so it is checked
    instead: for every route, build a concrete path it would serve and confirm no route
    declared earlier also matches it.
    """
    import re
    app = create_app(cfg)
    # The v1 routes live on the included router, not on `app.routes` — reading the app's own
    # route list finds about thirty of them and silently checks almost nothing.
    included = [r for r in app.routes if hasattr(r, "original_router")]
    assert included, "the v1 router is no longer included this way — fix this test"
    routes = [r for r in included[0].original_router.routes
              if getattr(r, "path", "").startswith("/v1/") and getattr(r, "methods", None)]
    assert len(routes) > 400, f"only found {len(routes)} routes to check"

    shadowed = []
    for index, route in enumerate(routes):
        if not [seg for seg in route.path.split("/") if seg and not seg.startswith("{")]:
            continue
        # A path this route serves, with each parameter filled by something that cannot be
        # mistaken for a literal segment anywhere.
        concrete = re.sub(r"\{[^}]+\}", "0a1b2c3d", route.path)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            for earlier in routes[:index]:
                if method not in earlier.methods:
                    continue
                match, _ = earlier.matches({"type": "http", "method": method,
                                            "path": concrete, "path_params": {},
                                            "root_path": ""})
                if match.name == "FULL":
                    shadowed.append(
                        f"{method} {route.path} is unreachable: {earlier.path} is declared "
                        f"above it and also matches {concrete}")
                    break
    assert not shadowed, "\n".join(shadowed)


def test_minting_a_pass_is_not_a_get(crew):
    """It creates a capability. On a GET that is CSRF-able from any page a member visits,
    and cacheable by anything in between."""
    client, people, crew_id = crew
    assert client.get(f"/v1/crews/{crew_id}/guest-pass",
                      headers=people["ana"]["h"]).status_code in (404, 405)
