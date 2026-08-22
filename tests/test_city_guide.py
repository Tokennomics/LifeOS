"""City guides — the fourteen endpoints that branched on the word "munich".

Say "munich" and you got hand-written Isar river swims and Krautrock nights; say anything
else and you got Edinburgh's. Fourteen ways of asking one question — *what is here, of this
kind?* — answered fourteen times with a literal.

They run over the two real sources now: places seeded from OpenStreetMap, and what people
and venue feeds actually put on the board. The tests that matter are the ones proving a view
cannot invent its own contents: an unmapped city has no trails, an unmatched listing does
not appear under vinyl, and the two views whose data does not exist at all say so instead of
approximating it.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import guide, places

PW = "correct-horse-battery"

GEOCODE = {"results": [{"name": "Lisbon", "country": "Portugal",
                        "latitude": 38.72, "longitude": -9.13}]}


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


def _soon(hours=5):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=hours)).isoformat()


def _seed(graph, category, name):
    payload = {"elements": [{"type": "node", "id": abs(hash(name)) % 100000,
                             "lat": 38.71, "lon": -9.14, "tags": {"name": name}}]}
    return places.seed(graph, "Lisbon", category=category,
                       geocode_fetch=lambda u, p: GEOCODE,
                       overpass_fetch=lambda u, q: payload)


# ---- a view cannot invent its contents ---------------------------------------

def test_an_unseeded_city_has_no_trails(city):
    """It returned walks with distances, difficulty ratings and "GPX cached" for every city
    on earth. A city nobody has mapped has no trails, and that is the answer."""
    client, people = city
    body = client.post("/v1/seeding/wild-nature-trails", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["empty"] is True
    assert body["places"] == [] and body["events"] == []


def test_no_view_names_a_place_that_was_never_mapped(city):
    client, people = city
    text = client.post("/v1/seeding/underground-vinyl-radar", json={"city": "Munich"},
                       headers=people["ana"]["h"]).text
    for invented in ("Unter Deck", "Krautrock", "Isar", "Flaucher", "Perlacher"):
        assert invented not in text


def test_saying_munich_no_longer_changes_the_answer(city):
    """The actual defect: the handler branched on a substring of the request."""
    client, people = city
    munich = client.post("/v1/seeding/wild-nature-trails", json={"city": "Munich"},
                         headers=people["ana"]["h"]).json()
    lisbon = client.post("/v1/seeding/wild-nature-trails", json={"city": "Lisbon"},
                         headers=people["ana"]["h"]).json()
    assert munich["places"] == lisbon["places"] == []
    assert munich["city"] == "munich" and lisbon["city"] == "lisbon"


def test_a_mapped_trail_appears(city):
    client, people = city
    _seed(client.app.state.graph, "trail", "The coast path")
    body = client.post("/v1/seeding/wild-nature-trails", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert [p["name"] for p in body["places"]] == ["The coast path"]
    assert body["empty"] is False


def test_a_mapped_library_appears_under_literary_and_not_under_trails(city):
    """Views must not become one shared query — the whole point is that they differ."""
    client, people = city
    _seed(client.app.state.graph, "library", "The reading room")
    lit = client.post("/v1/seeding/literary-salon-radar", json={"city": "Lisbon"},
                      headers=people["ana"]["h"]).json()
    trails = client.post("/v1/seeding/wild-nature-trails", json={"city": "Lisbon"},
                         headers=people["ana"]["h"]).json()
    assert [p["name"] for p in lit["places"]] == ["The reading room"]
    assert trails["places"] == []


def test_a_matching_meetup_appears_in_its_view(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Vinyl listening night",
                      "starts_at": _soon()}, headers=people["bruno"]["h"])
    body = client.post("/v1/seeding/underground-vinyl-radar", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert [m["title"] for m in body["meetups"]] == ["Vinyl listening night"]
    assert "vinyl" in body["meetups"][0]["matched_on"]


def test_an_unrelated_meetup_does_not(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Bouldering", "starts_at": _soon()},
                headers=people["bruno"]["h"])
    body = client.post("/v1/seeding/underground-vinyl-radar", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["meetups"] == []


def test_the_empty_answer_distinguishes_an_unmapped_city_from_a_quiet_one(city):
    """"No trails mapped here" and "nobody has proposed a walk" are different problems with
    different fixes, so the suggestion says which one it is."""
    client, people = city
    trails = client.post("/v1/seeding/wild-nature-trails", json={"city": "Lisbon"},
                         headers=people["ana"]["h"]).json()
    vinyl = client.post("/v1/seeding/underground-vinyl-radar", json={"city": "Lisbon"},
                        headers=people["ana"]["h"]).json()
    assert "map" in trails["suggestion"]
    assert "Propose" in vinyl["suggestion"]


def test_places_carry_attribution_when_there_are_any(city):
    client, people = city
    _seed(client.app.state.graph, "trail", "The coast path")
    body = client.post("/v1/seeding/wild-nature-trails", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert "OpenStreetMap" in body["attribution"]


def test_every_view_asks_for_a_city_rather_than_defaulting_to_one(city):
    client, people = city
    for path in ("/v1/seeding/wild-nature-trails", "/v1/seeding/underground-vinyl-radar",
                 "/v1/seeding/culinary-popup-drops", "/v1/seeding/literary-salon-radar",
                 "/v1/seeding/city-culture-guide", "/v1/seeding/tastemaker-curation",
                 "/v1/seeding/recurring-gravity-hubs"):
        body = client.post(path, json={}, headers=people["ana"]["h"]).json()
        assert body["needs_city"] is True, path


def test_the_view_list_is_discoverable(city):
    client, people = city
    views = client.get("/v1/city/guide/views", headers=people["ana"]["h"]).json()["views"]
    assert {v["view"] for v in views} >= {"trails", "vinyl", "food", "literary", "culture"}


def test_an_unknown_view_is_refused(graph):
    with pytest.raises(guide.GuideError):
        guide.view(graph, "Lisbon", "teleportation")


def test_a_view_needs_a_city(graph):
    with pytest.raises(guide.GuideError):
        guide.view(graph, "", "trails")


# ---- what is busiest ---------------------------------------------------------

def test_busiest_ranks_by_who_said_yes(city):
    """It reported trending venues with view counts and a virality index. Nothing counts
    views or shares here; what is real is how many people said they are going."""
    client, people = city
    quiet = client.post("/v1/city/meetups",
                        json={"city": "Lisbon", "title": "Quiet one",
                              "starts_at": _soon()},
                        headers=people["ana"]["h"]).json()
    busy = client.post("/v1/city/meetups",
                       json={"city": "Lisbon", "title": "The big one",
                             "starts_at": _soon()},
                       headers=people["bruno"]["h"]).json()
    client.post("/v1/city/meetups/join", json={"meetup_id": busy["meetup_id"]},
                headers=people["ana"]["h"])

    body = client.post("/v1/seeding/social-viral-pulse", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert [m["title"] for m in body["meetups"]][0] == "The big one"
    assert body["no_virality_index"]
    assert "virality_index" not in body and "view_count" not in body
    assert quiet["meetup_id"]


# ---- the two with no source at all -------------------------------------------

def test_footfall_says_it_has_no_sensor(city):
    """It reported live crowd density per venue with anomaly percentages. There is no source
    for that and no honest way to infer it."""
    client, people = city
    body = client.post("/v1/seeding/live-footfall-anomalies", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["available"] is False
    assert "sensor" in body["reason"]
    assert "anomaly_detector_active" not in body


def test_footfall_hands_back_the_nearest_real_thing(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "A plan", "starts_at": _soon()},
                headers=people["bruno"]["h"])
    body = client.post("/v1/seeding/live-footfall-anomalies", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert [m["title"] for m in body["instead"]["meetups"]] == ["A plan"]


def test_the_press_scraper_does_not_scrape(city):
    """Scraping publications with no agreement is somebody else's work taken without
    asking. Subscribing to a feed they publish is the same content, offered."""
    client, people = city
    body = client.post("/v1/seeding/editorial-press-scraper", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["available"] is False
    assert "scrape" in body["reason"]


def test_the_press_endpoint_still_finds_a_published_feed(cfg, monkeypatch):
    """The useful half survives: give it a site and it looks for a feed that site offers."""
    from modules.feeds import ingest
    monkeypatch.setattr(ingest, "discover_feeds",
                        lambda *a, **k: {"found": ["https://x.example/events.ics"]})
    client = TestClient(create_app({**cfg, "gateway": {"auth_token": "op"}}))
    body = client.post("/v1/seeding/editorial-press-scraper",
                       json={"url": "https://x.example", "city": "Lisbon"},
                       headers={"Authorization": "Bearer op"}).json()
    assert body["instead"]["found"] == ["https://x.example/events.ics"]


def test_discovering_a_feed_is_operator_only(city):
    client, people = city
    res = client.post("/v1/seeding/editorial-press-scraper",
                      json={"url": "https://x.example"}, headers=people["ana"]["h"])
    assert res.status_code == 403


# ---- the fabricated SSO endpoint is gone -------------------------------------

def test_the_fake_sso_endpoint_no_longer_exists(city):
    """It returned `authenticated: True`, a user id derived from hash(email) and "Cloud
    multi-device sync active" — with no token, no session and no provider involved. The PWA
    stopped calling it in August; the endpoint stayed reachable by anything else, which is
    the part that mattered."""
    client, people = city
    res = client.post("/v1/auth/social-sso",
                      json={"provider": "google", "identifier": "a@b.com"},
                      headers=people["ana"]["h"])
    assert res.status_code == 404


def test_real_sign_in_still_works(city):
    """Removing the theatre must not touch the door."""
    client, _ = city
    res = client.post("/v1/auth/login", json={"handle": "ana", "password": PW})
    assert res.status_code == 200 and res.json()["token"]


# ---- a helper that vanishes must not wait for a user to find it --------------

def test_no_route_references_a_name_that_does_not_exist(cfg):
    """Twice while building this, a shared helper was silently deleted.

    Both times it was a `def` sitting between an endpoint and the next `@router` decorator,
    and both times an edit that replaced the endpoint above it took the helper with it. The
    app still imported cleanly — a nested function's free name is resolved at *call* time —
    so the only symptom was a 500 the first time somebody hit that route.

    Python compiles a reference to a missing enclosing local as a global load. Walking every
    handler's bytecode for global loads that resolve to neither a module global nor a
    builtin catches exactly that, before it reaches anybody.
    """
    import builtins
    import dis

    from fastapi.routing import APIRoute

    app = create_app(cfg)

    # The v1 routes live on the INCLUDED router, not on `app.routes` — walking the app
    # directly finds about thirty of them and checks almost nothing. This guard was written
    # against `app.routes` and was therefore vacuous from the day it was added: it did not
    # catch the third occurrence of the very bug it exists for, `_ai_caller` deleted by an
    # edit to the endpoint above it. The route-shadowing guard had the same defect.
    routes = list(app.routes)
    for candidate in app.routes:
        original = getattr(candidate, "original_router", None)
        if original is not None:
            routes.extend(original.routes)
    checked = [r for r in routes if isinstance(r, APIRoute)]
    assert len(checked) > 400, (
        f"only {len(checked)} routes reached — this guard is not seeing the v1 router")

    def global_loads(code):
        """Every global name this code loads, including from nested code objects.

        Recursion is the whole point: almost every handler in this file wraps its work in
        `guard(lambda: ...)`, and a lambda is a separate code object hanging off
        `co_consts`. Inspecting only the handler's own bytecode therefore saw none of the
        calls that matter — which is the second reason this guard never fired.
        """
        for instruction in dis.get_instructions(code):
            if instruction.opname == "LOAD_GLOBAL":
                yield instruction.argval
        for const in code.co_consts:
            if hasattr(const, "co_code"):
                yield from global_loads(const)

    missing = []
    for route in checked:
        handler = route.endpoint
        for name in global_loads(handler.__code__):
            if name in handler.__globals__ or hasattr(builtins, name):
                continue
            missing.append(f"{route.path} references {name!r}")

    assert missing == [], "handlers reference names that do not exist: " + "; ".join(missing)
