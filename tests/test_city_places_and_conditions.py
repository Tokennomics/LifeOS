"""Third places and conditions — the two things a city can have with no users at all.

Every test here injects the HTTP response, the way `ingest.sync(text=...)` already lets feed
tests run without a network. That is not only convenience: the sandbox this was written in
answers 403 to the CONNECT for overpass-api.de and api.open-meteo.com, so the live calls are
genuinely unverified and the parsing has to be exercised against the documented shapes.

The properties worth pinning are the ones the old endpoints got wrong:

- a count is a count, not 160 for every city;
- an attribute OSM does not have is absent, not defaulted — the old directory claimed
  "Live Opening Hours & Wi-Fi Speeds Verified" for places it had never fetched;
- a missing reading produces no trigger, rather than a plausible one;
- seeding twice updates instead of doubling, because an operator will run it twice.
"""

import datetime

import pytest

from modules.city import chat, conditions, places
from modules.feeds.providers import openmeteo, overpass

GEOCODE = {"results": [{"name": "Lisbon", "country": "Portugal", "admin1": "Lisboa",
                        "latitude": 38.7167, "longitude": -9.1333,
                        "timezone": "Europe/Lisbon"}]}

OVERPASS = {"elements": [
    {"type": "node", "id": 1, "lat": 38.71, "lon": -9.14,
     "tags": {"name": "Fabrica", "amenity": "cafe", "opening_hours": "Mo-Fr 08:00-18:00"}},
    {"type": "way", "id": 2, "center": {"lat": 38.72, "lon": -9.15},
     "tags": {"name": "Miradouro", "tourism": "viewpoint"}},
    # No name: a directory of unnamed dots is not a directory.
    {"type": "node", "id": 3, "lat": 38.73, "lon": -9.16, "tags": {"amenity": "cafe"}},
]}

FORECAST = {
    "current": {"time": "2026-08-13T18:00", "temperature_2m": 24.1,
                "apparent_temperature": 24.9, "wind_speed_10m": 11.2,
                "cloud_cover": 12, "precipitation": 0.0},
    "daily": {"sunrise": ["2026-08-13T06:52"], "sunset": ["2026-08-13T20:31"],
              "temperature_2m_max": [26.4], "precipitation_probability_max": [5]},
}

MARINE = {"current": {"time": "2026-08-13T18:00", "wave_height": 1.4,
                      "wave_period": 9.2, "wave_direction": 292}}


def _geo(url, params):
    return GEOCODE


def _forecast(url, params):
    return FORECAST


def _marine(url, params):
    return MARINE


def _overpass(url, query):
    return OVERPASS


def _seed(graph, city="Lisbon", **kw):
    return places.seed(graph, city, geocode_fetch=_geo, overpass_fetch=_overpass, **kw)


def _read(graph, city="Lisbon", **kw):
    return conditions.read(graph, city, geocode_fetch=_geo, forecast_fetch=_forecast,
                           marine_fetch=_marine, **kw)


# ---- parsing the two APIs ---------------------------------------------------

def test_geocoding_places_a_city():
    """The endpoint this replaces had two cities in an if/else, and everything that was not
    Munich silently got Edinburgh's coordinates."""
    out = openmeteo.geocode("Lisbon", fetch=_geo)
    assert out["status"] == "ok"
    assert out["places"][0]["lat"] == 38.72


def test_an_unknown_city_is_not_found_rather_than_guessed():
    out = openmeteo.geocode("Xyzzy", fetch=lambda u, p: {"results": []})
    assert out["status"] == "not_found" and out["places"] == []


def test_a_missing_reading_is_none_not_zero():
    """"Wind: 0 km/h" is a specific claim about a still day. A field the API did not send
    has to come back missing, or every plausible default becomes a measurement."""
    out = openmeteo.forecast(0, 0, fetch=lambda u, p: {"current": {"temperature_2m": 20}})
    assert out["temp_c"] == 20.0
    assert out["wind_kmh"] is None and out["cloud_pct"] is None


def test_an_unreachable_api_is_a_status_not_an_exception():
    def boom(url, params):
        raise OSError("no route to host")
    assert "fetch failed" in openmeteo.forecast(0, 0, fetch=boom)["status"]
    assert "fetch failed" in openmeteo.geocode("Lisbon", fetch=boom)["status"]


def test_inland_marine_is_no_data_rather_than_flat_sea():
    out = openmeteo.marine(48.13, 11.58, fetch=lambda u, p: {"current": {}})
    assert out["status"] == "no_data"
    assert "wave_height_m" not in out


def test_overpass_query_is_bounded_and_capped():
    """An unbounded Overpass query is how one instance rate-limits everybody."""
    query = overpass.build_query(38.7, -9.1, "coffee", 3000)
    assert "around:3000" in query
    assert f"timeout:{overpass.TIMEOUT_S}" in query
    assert f"out center {overpass.MAX_ELEMENTS}" in query


def test_overpass_asks_for_ways_and_relations_too():
    """A park is a way and a market is often a relation. Asking only for nodes is how a
    query for parks comes back nearly empty and reads as "this city has none"."""
    assert overpass.build_query(38.7, -9.1, "park").startswith("[out:json]")
    assert "nwr(" in overpass.build_query(38.7, -9.1, "park")


def test_an_unknown_category_is_refused():
    with pytest.raises(ValueError):
        overpass.build_query(38.7, -9.1, "teleportation")


def test_a_place_with_no_name_is_skipped():
    items = overpass.normalise(OVERPASS, "coffee")
    assert [i["name"] for i in items] == ["Fabrica", "Miradouro"]


def test_a_way_uses_its_centre_point():
    items = overpass.normalise(OVERPASS, "coffee")
    assert items[1]["lat"] == 38.72


def test_an_untagged_attribute_is_absent_rather_than_defaulted():
    """The old directory claimed "Live Opening Hours & Wi-Fi Speeds Verified" for places it
    had never fetched. OSM either has the hours or it does not."""
    items = overpass.normalise(OVERPASS, "coffee")
    assert items[0]["opening_hours"] == "Mo-Fr 08:00-18:00"
    assert "opening_hours" not in items[1]


# ---- seeding -----------------------------------------------------------------

def test_seeding_stores_real_places(graph):
    out = _seed(graph, category="coffee")
    assert out["added"] == 2
    listed = places.listing(graph, "Lisbon")
    assert [p["name"] for p in listed["places"]] == ["Fabrica", "Miradouro"]


def test_seeding_twice_updates_rather_than_doubles(graph):
    """An operator will run this twice. Idempotence is the expected case, not a bug report."""
    _seed(graph, category="coffee")
    second = _seed(graph, category="coffee")
    assert second["added"] == 0 and second["updated"] == 2
    assert places.listing(graph, "Lisbon")["total"] == 2


def test_the_breakdown_is_a_count_of_what_is_there(graph):
    """It reported 42 specialty coffee workspaces and 24 viewpoints, for every city."""
    _seed(graph, category="coffee")
    assert places.listing(graph, "Lisbon")["breakdown"] == {"coffee": 2}


def test_an_unseeded_city_is_empty_and_says_so(graph):
    listed = places.listing(graph, "Porto")
    assert listed["empty"] is True and listed["places"] == []
    assert "seeded" in listed["suggestion"]


def test_seeding_never_claims_verification(graph):
    out = _seed(graph, category="coffee")
    assert out["verified"] is False
    assert "OpenStreetMap" in out["attribution"]


def test_places_carry_attribution(graph):
    """OSM's licence requires it, and it is also the honest answer to "who says so"."""
    _seed(graph, category="coffee")
    assert "OpenStreetMap" in places.listing(graph, "Lisbon")["attribution"]


def test_a_city_that_cannot_be_placed_seeds_nothing(graph):
    out = places.seed(graph, "Xyzzy", geocode_fetch=lambda u, p: {"results": []},
                      overpass_fetch=_overpass)
    assert out["added"] == 0 and out["status"] == "not_found"


def test_one_failing_category_does_not_blank_the_others(graph):
    calls = {"n": 0}

    def flaky(url, query):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("overpass timeout")
        return OVERPASS

    out = places.seed(graph, "Lisbon", geocode_fetch=_geo, overpass_fetch=flaky)
    statuses = {c["status"] for c in out["categories"].values()}
    assert "ok" in statuses and any(s.startswith("fetch failed") for s in statuses)
    assert out["added"] > 0


def test_seeding_needs_a_city(graph):
    with pytest.raises(places.PlacesError):
        places.seed(graph, "")


def test_an_unknown_category_is_refused_at_the_module_edge(graph):
    with pytest.raises(places.PlacesError):
        places.seed(graph, "Lisbon", category="teleportation", geocode_fetch=_geo)


def test_pruning_is_explicit_rather_than_automatic(graph):
    """A café must not vanish because one Overpass query timed out, which is what "delete
    anything missing from this response" would do."""
    _seed(graph, category="coffee")
    assert places.prune(graph, "Lisbon", older_than_days=90)["removed"] == 0
    session = places._sys(graph)
    for row in session.find_entities("content", {"type": places.RECORD}, limit=10):
        session.update_entity(row["id"], {"refreshed_at": "2020-01-01T00:00:00+00:00"},
                              source="test")
    assert places.prune(graph, "Lisbon", older_than_days=1)["removed"] == 2


def test_cities_do_not_bleed_into_each_other(graph):
    _seed(graph, "Lisbon", category="coffee")
    assert places.listing(graph, "Porto")["places"] == []


# ---- conditions --------------------------------------------------------------

def test_conditions_report_what_was_measured(graph):
    out = _read(graph)
    assert out["available"] is True
    assert out["weather"]["temp_c"] == 24.1
    assert out["marine"]["wave_height_m"] == 1.4


def test_conditions_are_cached_so_one_screen_is_one_fetch(graph):
    calls = {"n": 0}

    def counted(url, params):
        calls["n"] += 1
        return FORECAST

    conditions.read(graph, "Lisbon", geocode_fetch=_geo, forecast_fetch=counted,
                    marine_fetch=_marine)
    conditions.read(graph, "Lisbon", geocode_fetch=_geo, forecast_fetch=counted,
                    marine_fetch=_marine)
    assert calls["n"] == 1


def test_refresh_bypasses_the_cache(graph):
    calls = {"n": 0}

    def counted(url, params):
        calls["n"] += 1
        return FORECAST

    conditions.read(graph, "Lisbon", geocode_fetch=_geo, forecast_fetch=counted,
                    marine_fetch=_marine)
    conditions.read(graph, "Lisbon", refresh=True, geocode_fetch=_geo,
                    forecast_fetch=counted, marine_fetch=_marine)
    assert calls["n"] == 2


def test_a_stale_cache_is_refetched(graph):
    _read(graph)
    session = conditions._sys(graph)
    row = session.find_entities("content", {"type": conditions.RECORD}, limit=1)[0]
    old = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(hours=3)).isoformat()
    session.update_entity(row["id"], {"fetched_at": old}, source="test")
    assert _read(graph)["cached"] is False


def test_an_unreachable_forecast_is_not_available(graph):
    def boom(url, params):
        raise OSError("down")
    out = conditions.read(graph, "Lisbon", geocode_fetch=_geo, forecast_fetch=boom,
                          marine_fetch=_marine)
    assert out["available"] is False


def test_a_failed_fetch_is_never_cached_as_a_reading(graph):
    """The old ingest endpoint fell back to a hardcoded 22.4 °C on any failure. Storing that
    would make the next reader believe it was measured."""
    def boom(url, params):
        raise OSError("down")
    conditions.read(graph, "Lisbon", geocode_fetch=_geo, forecast_fetch=boom,
                    marine_fetch=_marine)
    assert conditions._sys(graph).find_entities(
        "content", {"type": conditions.RECORD}, limit=1) == []


# ---- triggers ----------------------------------------------------------------

def test_a_trigger_quotes_its_reading_and_its_rule(graph):
    """"PRIME CONDITIONS" was an assertion. "1.4 m, which is over the 0.8 m this fires at"
    is a reading plus a rule the reader can disagree with."""
    out = conditions.triggers(graph, "Lisbon", geocode_fetch=_geo,
                              forecast_fetch=_forecast, marine_fetch=_marine)
    surf = [t for t in out["triggers"] if t["trigger"] == "surf"][0]
    assert surf["reading"] == "wave height 1.4 m"
    assert str(conditions.THRESHOLDS["surf_wave_m"]) in surf["rule"]


def test_a_flat_sea_fires_no_surf_trigger(graph):
    flat = {"current": {"time": "x", "wave_height": 0.2, "wave_period": 4}}
    out = conditions.triggers(graph, "Lisbon", geocode_fetch=_geo,
                              forecast_fetch=_forecast,
                              marine_fetch=lambda u, p: flat)
    assert [t["trigger"] for t in out["triggers"] if t["trigger"] == "surf"] == []


def test_a_missing_reading_fires_no_trigger_at_all(graph):
    """The one place where saying nothing is strictly better than guessing."""
    bare = {"current": {"time": "x"}, "daily": {}}
    out = conditions.triggers(graph, "Lisbon", geocode_fetch=_geo,
                              forecast_fetch=lambda u, p: bare,
                              marine_fetch=lambda u, p: {"current": {}})
    assert out["triggers"] == []
    assert out["available"] is True          # we asked and got an answer; it was thin


def test_no_weather_source_claims_nothing(graph):
    def boom(url, params):
        raise OSError("down")
    out = conditions.triggers(graph, "Lisbon", geocode_fetch=_geo, forecast_fetch=boom,
                              marine_fetch=boom)
    assert out["available"] is False and out["triggers"] == []
    assert "nothing is claimed" in out["suggestion"]


def test_a_clear_evening_is_a_sunset_trigger(graph):
    out = conditions.triggers(graph, "Lisbon", geocode_fetch=_geo,
                              forecast_fetch=_forecast, marine_fetch=_marine)
    assert any(t["trigger"] == "sunset" for t in out["triggers"])


def test_an_overcast_evening_is_not(graph):
    grey = {**FORECAST, "current": {**FORECAST["current"], "cloud_cover": 95}}
    out = conditions.triggers(graph, "Lisbon", geocode_fetch=_geo,
                              forecast_fetch=lambda u, p: grey, marine_fetch=_marine)
    assert not any(t["trigger"] == "sunset" for t in out["triggers"])


def test_conditions_need_a_city(graph):
    with pytest.raises(conditions.ConditionsError):
        conditions.read(graph, "")


def test_the_city_key_is_the_same_slug_the_rest_of_the_app_uses(graph):
    """`São Paulo` and `Sao Paulo` must not become two cities here either."""
    assert _read(graph, "São Paulo")["city"] == chat.slug("Sao Paulo")


# ---- the provider registry ---------------------------------------------------

def test_the_no_key_providers_report_that_they_need_none():
    from modules.feeds import providers
    by_name = {p["name"]: p for p in providers.status()}
    assert by_name["openmeteo"]["needs_key"] is False
    assert by_name["overpass"]["needs_key"] is False
    assert by_name["ticketmaster"]["needs_key"] is True


def test_a_weather_provider_cannot_be_synced_as_events(graph):
    """They belong in one registry — they are all "outside data" — but handing a forecast to
    the event sync should be a clear no rather than a TypeError."""
    from modules.feeds import ingest
    with pytest.raises(ValueError, match="not events"):
        ingest.sync_provider(graph, "openmeteo", city="Lisbon")
