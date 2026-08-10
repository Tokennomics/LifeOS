"""The weekend digest over a real graph, across real accounts.

The interesting cases are all about what must NOT be in it: someone else's private event,
your own dentist appointment in the copy you send a friend, and a city you aren't in.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.discover import discover
from modules.weekend import core, digest
from substrate.graph import Graph

PW = "correct-horse-battery"
TUE = "2026-08-04T09:00:00+00:00"          # weekend is Fri 7 – Sun 9 August
FRI_NIGHT = "2026-08-07T20:00:00+00:00"
SAT_NIGHT = "2026-08-08T21:00:00+00:00"
NEXT_SAT = "2026-08-15T21:00:00+00:00"
LAST_TUE = "2026-08-04T19:00:00+00:00"     # midweek: on nobody's weekend


@pytest.fixture
def world(graph):
    ana = accounts.register(graph, "ana", PW)
    bruno = accounts.register(graph, "bruno", PW)
    return {"ana": Graph(graph.conn, graph.bus, default_owner=ana["owner_id"]),
            "bruno": Graph(graph.conn, graph.bus, default_owner=bruno["owner_id"]),
            "ana_id": ana["account_id"], "bruno_id": bruno["account_id"], "root": graph}


def _publish(g, title, start, city="Lisbon", visibility="public", topic="", place=""):
    return discover.publish_event(g, title, start=start, city=city, topic=topic,
                                  place=place, visibility=visibility)["event_id"]


def _weekend(g, **kw):
    return digest.weekend(g, now=TUE, **kw)


# ---- the basic answer --------------------------------------------------------

def test_it_shows_what_is_on_across_accounts(world):
    _publish(world["bruno"], "Warehouse party", FRI_NIGHT, place="Cais do Sodré")
    _publish(world["bruno"], "Sushi night", SAT_NIGHT, place="Bairro Alto")

    d = _weekend(world["ana"], city="Lisbon")
    assert d["counts"]["open"] == 2
    assert [i["title"] for i in d["days"][0]["open"]] == ["Warehouse party"]
    assert [i["title"] for i in d["days"][1]["open"]] == ["Sushi night"]
    assert d["days"][2]["open"] == []


def test_midweek_and_next_weekend_are_not_this_weekend(world):
    _publish(world["bruno"], "Tuesday pub quiz", LAST_TUE)
    _publish(world["bruno"], "Next Saturday", NEXT_SAT)
    assert _weekend(world["ana"], city="Lisbon")["counts"]["open"] == 0


def test_offset_reaches_next_weekend(world):
    _publish(world["bruno"], "Next Saturday", NEXT_SAT)
    d = _weekend(world["ana"], city="Lisbon", offset=1)
    assert [i["title"] for i in d["days"][1]["open"]] == ["Next Saturday"]
    assert d["when_label"] == "next weekend"


def test_another_city_is_someone_elses_weekend(world):
    _publish(world["bruno"], "Berlin thing", SAT_NIGHT, city="Berlin")
    assert _weekend(world["ana"], city="Lisbon")["counts"]["open"] == 0
    assert _weekend(world["ana"], city="Berlin")["counts"]["open"] == 1
    assert _weekend(world["ana"])["counts"]["open"] == 1, "no city means everywhere"


# ---- what must not be in it --------------------------------------------------

def test_a_private_event_is_never_in_anyone_elses_weekend(world):
    _publish(world["bruno"], "Bruno's private thing", SAT_NIGHT, visibility="private")
    d = _weekend(world["ana"], city="Lisbon")
    assert d["counts"]["open"] == 0
    assert "private thing" not in d["text"]


def test_your_own_plans_are_yours_and_are_shown_to_you(world):
    """A digest that recommends into a clash is worse than no digest."""
    world["ana"].session("t", {"events:write", "events:read"}).create_entity(
        "event", {"type": "meet", "title": "Dinner with Marta", "start": SAT_NIGHT,
                  "place": "Alfama"}, source="test")
    d = _weekend(world["ana"], city="Lisbon")
    assert [i["title"] for i in d["days"][1]["yours"]] == ["Dinner with Marta"]
    assert _weekend(world["bruno"], city="Lisbon")["counts"]["yours"] == 0


def test_an_untitled_calendar_block_still_counts_as_busy(world):
    """ICS sync stores no title by default — handing a work calendar's subject lines to a
    personal graph should be opt-in. An untitled busy block is still a busy block."""
    world["ana"].session("t", {"events:write", "events:read"}).create_entity(
        "event", {"start": SAT_NIGHT, "busy": True, "source": "ics"}, source="ics-sync")
    d = _weekend(world["ana"], city="Lisbon")
    assert [i["title"] for i in d["days"][1]["yours"]] == ["Busy"]


# ---- the thing you send a friend ---------------------------------------------

def test_the_shareable_text_leaves_your_own_plans_out(world):
    """This is the whole reason `shareable` exists rather than sending `text` directly."""
    _publish(world["bruno"], "Warehouse party", FRI_NIGHT)
    world["ana"].session("t", {"events:write", "events:read"}).create_entity(
        "event", {"type": "meet", "title": "Dentist", "start": SAT_NIGHT}, source="test")

    mine = _weekend(world["ana"], city="Lisbon")
    assert "Dentist" in mine["text"]

    out = digest.shareable(world["ana"], city="Lisbon", now=TUE)
    assert "Dentist" not in out["text"]
    assert "Warehouse party" in out["text"]
    assert out["includes_your_own_plans"] is False


def test_you_can_opt_in_to_sharing_your_own_plans(world):
    world["ana"].session("t", {"events:write", "events:read"}).create_entity(
        "event", {"type": "meet", "title": "Dentist", "start": SAT_NIGHT}, source="test")
    out = digest.shareable(world["ana"], city="Lisbon", now=TUE, include_yours=True)
    assert "Dentist" in out["text"] and out["includes_your_own_plans"] is True


def test_the_text_is_a_message_not_a_screen(world):
    _publish(world["bruno"], "Warehouse party", FRI_NIGHT, place="Cais do Sodré")
    text = digest.shareable(world["ana"], city="Lisbon", now=TUE)["text"]
    assert text.startswith("Lisbon — this weekend (7–9 Aug)")
    assert "20:00 Warehouse party @ Cais do Sodré" in text
    assert max(len(line) for line in text.splitlines()) < 80


# ---- the empty weekend, which is the common case at the start ----------------

def test_an_empty_weekend_points_at_the_crews_who_could_fix_it(world):
    from modules.crews import crews
    crews.create(world["bruno"], "Lisbon Sushi Club", topic="sushi", city="Lisbon",
                 visibility="public", admission="open", admin_id=world["bruno_id"])

    d = _weekend(world["ana"], city="Lisbon")
    assert d["counts"]["open"] == 0 and d["counts"]["crews"] == 1
    assert "Lisbon Sushi Club" in d["text"]
    assert "Someone has to go first" in d["text"]


def test_an_empty_weekend_with_nothing_at_all_says_that_plainly(world):
    """LifeOS is not a scraper. An empty digest is an honest report that nobody published
    anything, and inventing events would hide exactly the signal that matters."""
    d = _weekend(world["ana"], city="Lisbon")
    assert "Nothing published for this weekend yet." in d["text"]


def test_opened_on_saturday_it_shows_what_is_left_not_what_was_missed(world):
    _publish(world["bruno"], "Friday party", FRI_NIGHT)
    _publish(world["bruno"], "Saturday sushi", SAT_NIGHT)
    world["ana"].session("t", {"events:write", "events:read"}).create_entity(
        "event", {"type": "meet", "title": "Dentist",
                  "start": "2026-08-08T10:00:00+00:00"}, source="test")

    d = digest.weekend(world["ana"], city="Lisbon", now="2026-08-08T15:00:00+00:00")
    assert d["trimmed_to_whats_left"] is True
    assert d["when_label"] == "rest of the weekend"
    assert "Friday party" not in d["text"] and "Dentist" not in d["text"]
    assert "Saturday sushi" in d["text"]
    assert [day["date"] for day in d["days"]] == ["2026-08-08", "2026-08-09"]


def test_a_weekend_that_has_not_started_is_never_trimmed(world):
    _publish(world["bruno"], "Friday party", FRI_NIGHT)
    d = _weekend(world["ana"], city="Lisbon")
    assert d["trimmed_to_whats_left"] is False
    assert d["when_label"] == "this weekend"
    assert "Friday party" in d["text"]


# ---- ranking -----------------------------------------------------------------

def test_everything_on_is_listed_even_if_it_matches_nothing_you_like(world):
    """`rank_feed` drops items that are neither interest-matched nor popular. Right for an
    infinite feed; wrong for a finite weekend — "what's on" has to mean everything."""
    _publish(world["bruno"], "Obscure poetry reading", SAT_NIGHT, topic="poetry")
    d = _weekend(world["ana"], city="Lisbon", interests=["climbing"])
    assert [i["title"] for i in d["days"][1]["open"]] == ["Obscure poetry reading"]


def test_the_popular_and_relevant_thing_comes_first(world):
    quiet = _publish(world["bruno"], "Quiet thing", SAT_NIGHT)
    loud = _publish(world["bruno"], "Climbing meetup", SAT_NIGHT, topic="climbing")
    for i in range(4):
        discover.mark_interest(world["bruno"], loud, f"p{i}")
    discover.mark_interest(world["bruno"], quiet, "p9")

    d = _weekend(world["ana"], city="Lisbon", interests=["climbing"])
    assert [i["title"] for i in d["days"][1]["open"]] == ["Climbing meetup", "Quiet thing"]


# ---- the gateway -------------------------------------------------------------

def test_the_endpoints_work(cfg):
    client = TestClient(create_app(cfg))
    r = client.get("/v1/weekend", params={"city": "Lisbon"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["days"]) in (2, 3) and "text" in body

    s = client.get("/v1/weekend/share", params={"city": "Lisbon"})
    assert s.status_code == 200
    assert s.json()["includes_your_own_plans"] is False


def test_the_share_endpoint_needs_an_explicit_opt_in_for_your_own_plans(cfg):
    client = TestClient(create_app(cfg))
    assert client.get("/v1/weekend/share").json()["includes_your_own_plans"] is False
    assert client.get("/v1/weekend/share",
                      params={"include_yours": "true"}).json()["includes_your_own_plans"] is True
