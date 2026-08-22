"""The last two endpoints that invented people.

`/ar/spatial-flares` returned three beacons rendered in 3D — "Elena R. (96% Match)" at 85
metres on a bearing of 42°, a venue at "88% Density", an audio space by "Alex & Crew", with
altitude offsets as though the app knew which floor they were on. There is no AR here, no
compass, and no position of any kind.

`/gallery/live-event-wall` returned two photos by Elena R. and Alex M. carrying "verified
PoP badges" — `POP-89F12A04` — proof-of-presence tokens nobody issued, verifying nothing.
There is no image pipeline in this app; a moment is a caption.
"""

import datetime

import pytest

from gateway import accounts
from modules.city import live, synergy
from modules.social import signals

PW = "correct-horse-battery"
INVENTED = ("elena", "alex m.", "alex & crew", "96%", "88%", "pop-", "spatial_radar",
            "bearing", "altitude", "distance_m", "miradouro rooftop bar")


@pytest.fixture
def people(graph):
    return {name: accounts.register(graph, name, PW)["account_id"]
            for name in ("ana", "bo")}


def _text(payload) -> str:
    """The response with its disclaimers stripped.

    These endpoints now say plainly what they are *not* doing — "no distance, no bearing
    and no radar" — which is worth keeping for whoever reads it, and which makes a
    whole-body substring search useless. The negative fields come out; what is left is what
    the endpoint actually claims.
    """
    return str({k: v for k, v in payload.items()
                if not k.startswith("no_") and k not in ("note", "suggestion")}).lower()


# ---- what is live around you --------------------------------------------------

def test_a_quiet_city_is_quiet(graph, people):
    """It rendered three beacons on any instance, including one installed a minute ago."""
    out = live.around(graph, "Lisbon", viewer_id=people["ana"])
    assert out["empty"] is True and out["count"] == 0
    assert out["suggestion"]
    for invented in INVENTED:
        assert invented not in _text(out)


def test_it_shows_what_people_actually_published(graph, people):
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=people["bo"], handle="bo")
    signals.post_moment(graph, "Lisbon", "sunset from the viewpoint",
                        account_id=people["bo"], handle="bo")
    out = live.around(graph, "Lisbon", viewer_id=people["ana"])
    assert out["count"] == 2
    assert {i["kind"] for i in out["live"]} == {"up for it", "posted"}
    assert all(i["handle"] == "bo" for i in out["live"])


def test_nothing_is_placed_in_space(graph, people):
    """Every number in the old response was decoration on somebody who was not there."""
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=people["bo"])
    out = live.around(graph, "Lisbon", viewer_id=people["ana"])
    assert out["coordinates"] is False
    assert out["augmented_reality"] is False
    assert out["no_position"]
    for field in ("distance_m", "bearing_deg", "altitude_offset_m", "ar_glyph"):
        assert field not in str(out["live"][0])


def test_an_expired_signal_is_gone(graph, people, monkeypatch):
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=people["bo"], hours=1)
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    monkeypatch.setattr(live, "_now", lambda: later)
    assert live.around(graph, "Lisbon", viewer_id=people["ana"])["empty"] is True


def test_a_withdrawn_signal_is_gone(graph, people):
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=people["bo"])
    synergy.close(graph, "Lisbon", "bouldering", account_id=people["bo"])
    assert live.around(graph, "Lisbon", viewer_id=people["ana"])["empty"] is True


def test_another_city_is_another_city(graph, people):
    synergy.open_to(graph, "Porto", "bouldering", account_id=people["bo"])
    assert live.around(graph, "Lisbon", viewer_id=people["ana"])["empty"] is True
    assert live.around(graph, "Porto", viewer_id=people["ana"])["count"] == 1


def test_with_no_city_it_asks_rather_than_guessing(graph, people):
    """`/weather/radar` already answers `needs_city` rather than picking one, and guessing
    is how somebody in Porto gets told what is happening 300 km away."""
    out = live.around(graph, "", viewer_id=people["ana"])
    assert out["needs_city"] is True
    assert out["live"] == [] and out["empty"] is True
    assert live.wall(graph, "", viewer_id=people["ana"])["needs_city"] is True


def test_your_own_things_are_marked_as_yours(graph, people):
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=people["ana"], handle="ana")
    out = live.around(graph, "Lisbon", viewer_id=people["ana"])
    assert out["live"][0]["mine"] is True


# ---- the wall -----------------------------------------------------------------

def test_the_wall_holds_captions_not_photos(graph, people):
    signals.post_moment(graph, "Lisbon", "sunset from the viewpoint",
                        account_id=people["bo"], handle="bo")
    out = live.wall(graph, "Lisbon", viewer_id=people["ana"])
    assert out["count"] == 1
    assert out["posts"][0]["caption"] == "sunset from the viewpoint"
    assert out["photos"] is False
    assert out["verified_presence"] is False
    for invented in INVENTED:
        assert invented not in _text(out)


def test_an_empty_wall_says_so(graph, people):
    out = live.wall(graph, "Lisbon", viewer_id=people["ana"])
    assert out["empty"] is True and out["posts"] == []
    assert out["suggestion"]


def test_the_wall_does_not_mint_a_presence_badge(graph, people):
    """`POP-89F12A04` was a token nobody issued, on no chain, verifying nothing."""
    signals.post_moment(graph, "Lisbon", "a caption", account_id=people["bo"])
    out = live.wall(graph, "Lisbon", viewer_id=people["ana"])
    assert "pop_badge" not in str(out)
    assert out["note"]


def test_an_expired_post_leaves_the_wall(graph, people, monkeypatch):
    signals.post_moment(graph, "Lisbon", "a caption", account_id=people["bo"])
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)
    monkeypatch.setattr(live, "_now", lambda: later)
    assert live.wall(graph, "Lisbon", viewer_id=people["ana"])["empty"] is True


# ---- over HTTP ---------------------------------------------------------------

def test_the_endpoints_answer_about_the_city_you_are_in(cfg, monkeypatch):
    """Both used to answer about Lisbon whoever asked. Guessing a city is how somebody in
    Porto gets told what is happening 300 km away."""
    from fastapi.testclient import TestClient
    from gateway import rate_limiter
    from gateway.main import create_app
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")

    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    # Nothing published anywhere: no city to guess, and nothing invented to fill it.
    flares = client.get("/v1/ar/spatial-flares", headers=h)
    assert flares.status_code == 200
    assert flares.json()["needs_city"] is True
    # Checked on the claims rather than the whole body: the response explains that it has
    # no distance and no bearing, so those words are legitimately present.
    for invented in ("elena", "96%", "spatial_radar", "distance_m"):
        assert invented not in _text(flares.json())

    wall = client.get("/v1/gallery/live-event-wall", headers=h)
    assert wall.status_code == 200
    for invented in ("elena", "alex m.", "pop-", "miradouro rooftop bar"):
        assert invented not in _text(wall.json())

    # Say you are in Porto — `synergy.city_for` reads announced presence, which is the
    # right semantic: "where you said you are", not "where you last published something".
    announced = client.post("/v1/city/around", json={"city": "Porto"}, headers=h)
    assert announced.status_code == 200, announced.text
    published = client.post("/v1/synergy/open-to",
                            json={"city": "Porto", "activity": "bouldering"}, headers=h)
    assert published.status_code == 200, published.text
    out = client.get("/v1/ar/spatial-flares", headers=h).json()
    assert out["city"] == "porto"
    assert out["count"] == 1

    # And an explicit city still wins.
    assert client.get("/v1/ar/spatial-flares?city=Lisbon",
                      headers=h).json()["city"] == "lisbon"


def test_the_globe_card_no_longer_hardcodes_a_world(cfg):
    """The card carried "115 Active Flares" and Lisbon/Tokyo/New York counts and
    temperatures written straight into the markup — not even fetched."""
    import pathlib
    app_js = (pathlib.Path(__file__).resolve().parent.parent
              / "surfaces" / "app" / "www" / "app.js").read_text(encoding="utf-8")
    for invented in ("115 Active Flares", "14 Flares", "28 Flares", "🇯🇵 Tokyo",
                     "🇺🇸 New York"):
        assert invented not in app_js
    assert 'data-act="show-globe"' in app_js
