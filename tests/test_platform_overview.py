"""The three dashboard reads: system status, the globe, and how the feed ranks.

All three were screens that told somebody a system was working. `/os/master-controller`
reported orchestration of "50+ subsystems" including BLE mesh, spatial audio and Apple Pay,
and closed with `system_health: "100% Operational (898+ Tests Verified)"`. A status page
that always says OK is worse than none: it is the one screen whose entire job is to be
believed.

`/city/live-globe` returned five hardcoded cities with coordinates and weather.
`/feed/transparent-rules` claimed to apply a ranking this app does not implement, stored
nothing, and called itself transparency.
"""

import pytest

from gateway import accounts
from modules.city import synergy
from modules.platform import overview

PW = "correct-horse-battery"
INVENTED = ("ai butler", "898", "100% operational", "ble 5.3", "airpods", "apple pay",
            "98/100", "24°c", "sunny", "3d_spatial_globe", "doomscroll",
            "real_world_weight", "proximity_bias")


@pytest.fixture
def account(graph):
    return accounts.register(graph, "ana", PW)["account_id"]


# ---- system status -----------------------------------------------------------

def test_a_capability_is_available_only_if_it_is_configured(graph, account, monkeypatch):
    monkeypatch.delenv("LIFEOS_TICKETMASTER_KEY", raising=False)
    out = overview.system(graph, account_id=account)
    listings = next(c for c in out["capabilities"] if c["name"] == "ticketed listings")
    assert listings["available"] is False

    monkeypatch.setenv("LIFEOS_TICKETMASTER_KEY", "a-key")
    out = overview.system(graph, account_id=account)
    listings = next(c for c in out["capabilities"] if c["name"] == "ticketed listings")
    assert listings["available"] is True


def test_the_things_this_app_cannot_do_are_listed_not_omitted(graph, account):
    """The old controller reported them as online. Dropping them silently would read as
    though they work."""
    out = overview.system(graph, account_id=account)
    named = {u["name"] for u in out["unavailable"]}
    assert "push notifications" in named
    assert "payments" in named
    assert "identity verification" in named
    assert all(u["why"] for u in out["unavailable"])


def test_nothing_reports_itself_as_operational(graph, account):
    out = overview.system(graph, account_id=account)
    text = str(out).lower()
    for invented in INVENTED:
        assert invented not in text
    assert "asserted" in out["health"]


def test_the_counts_are_counts(graph, account):
    out = overview.system(graph, account_id=account)
    assert out["counts"]["accounts"] == 1
    assert out["counts"]["crews"] == 0


# ---- the globe ---------------------------------------------------------------

def test_a_new_instance_has_nobody_anywhere(graph, account):
    """It reported 115 active beacons across five cities, on any deployment."""
    out = overview.globe(graph)
    assert out["empty"] is True and out["count"] == 0
    assert out["suggestion"]
    text = str(out).lower()
    for invented in ("lisbon", "tokyo", "new york", "38.722", "flares"):
        assert invented not in text


def test_a_city_appears_when_somebody_posts_in_it(graph, account):
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=account, handle="ana")
    out = overview.globe(graph)
    assert out["count"] == 1
    assert out["cities"][0]["city"] == "lisbon"
    assert out["cities"][0]["counts"]["open intents"] == 1
    assert out["cities"][0]["total"] == 1


def test_a_withdrawn_intent_does_not_keep_a_city_alive(graph, account):
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=account)
    synergy.close(graph, "Lisbon", "bouldering", account_id=account)
    assert overview.globe(graph)["empty"] is True


def test_the_globe_has_no_coordinates(graph, account):
    """The five sets of lat/lon were decoration on counts that were not real either."""
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=account)
    out = overview.globe(graph)
    assert out["coordinates"] is False
    assert "lat" not in str(out["cities"][0])


# ---- the feed rules ----------------------------------------------------------

def test_the_rules_come_from_the_code_that_ranks(graph):
    """Imported, not restated — so if the ranking changes, this changes with it."""
    from modules.discover import core
    out = overview.feed_rules()
    crowd = next(p for p in out["parts"] if p["part"] == "how many people are going")
    assert crowd["weights"]["most a crowd can add"] == core.POP_WEIGHT
    assert crowd["weights"]["headcount that earns half of it"] == core.POP_HALF

    match = next(p for p in out["parts"] if p["part"] == "interest match")
    assert match["weights"]["topic is your interest"] == core.TOPIC_HIT


def test_the_rules_describe_the_three_parts_that_actually_exist(graph):
    out = overview.feed_rules()
    assert [p["part"] for p in out["parts"]] == [
        "interest match", "how many people are going", "how soon it is"]
    assert out["excluded"]


def test_it_is_a_description_not_a_control_panel(graph):
    """It accepted a `real_world_weight` and a `proximity_bias` and stored neither, which is
    the opposite of transparency."""
    out = overview.feed_rules()
    assert out["settable"] is False
    assert out["why_not_settable"]
    text = str(out).lower()
    for invented in INVENTED:
        assert invented not in text


def test_the_claims_about_advertising_are_about_the_code(graph):
    out = overview.feed_rules()
    assert "no ad system" in out["no_advertising"]
    assert "session length" in out["no_engagement_optimisation"]
