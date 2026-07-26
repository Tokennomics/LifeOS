"""Feed — one ranked stream for where you are and where you're going to be."""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.discover import core, discover
from modules.reconnect import decay


def _iso(days: float) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=days)).isoformat()


NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()


def _item(title, topic="", city="Lisbon", start="", going=0, visibility="public"):
    return {"id": title, "kind": "event", "title": title, "topic": topic, "city": city,
            "start": start or _iso(2), "going_count": going, "visibility": visibility}


# ---- blending ---------------------------------------------------------------

def test_popularity_saturates():
    assert core.popularity_score(0) == 0.0
    assert core.popularity_score(4) == pytest.approx(core.POP_WEIGHT / 2)
    ten, hundred = core.popularity_score(10), core.popularity_score(100)
    assert hundred > ten
    assert hundred < core.POP_WEIGHT                      # never runs away
    assert (hundred - ten) < (ten - core.popularity_score(1))   # diminishing returns


def test_soonness_fades_with_distance():
    assert core.soon_score(_iso(0.1), NOW) > core.soon_score(_iso(3), NOW) > 0
    assert core.soon_score(_iso(30), NOW) == 0.0          # beyond the window
    assert core.soon_score("not-a-date", NOW) == 0.0      # tolerant of junk


def test_a_perfect_match_beats_a_crowd_you_dont_care_about():
    items = [_item("Massive rave", topic="techno", going=500),
             _item("Sushi night", topic="sushi", going=3)]
    out = core.rank_feed(items, ["sushi"], now=NOW)
    assert out[0]["title"] == "Sushi night"


def test_popularity_breaks_the_tie_between_equal_matches():
    items = [_item("Quiet sushi", topic="sushi", going=1, start=_iso(2)),
             _item("Busy sushi", topic="sushi", going=40, start=_iso(2))]
    out = core.rank_feed(items, ["sushi"], now=NOW)
    assert [i["title"] for i in out] == ["Busy sushi", "Quiet sushi"]


def test_feed_never_shows_private_or_past_or_pure_noise():
    items = [_item("Private thing", topic="sushi", visibility="private"),
             _item("Old sushi", topic="sushi", start=_iso(-5)),
             _item("Irrelevant empty event", topic="knitting", going=0)]
    assert core.rank_feed(items, ["sushi"], now=NOW) == []


def test_items_explain_themselves():
    out = core.rank_feed([_item("Sushi night", topic="sushi", going=12, start=_iso(1))],
                         ["sushi"], now=NOW)
    reasons = " | ".join(out[0]["reasons"])
    assert "matches sushi" in reasons and "12 interested" in reasons and "happening soon" in reasons
    assert out[0]["matched"] == ["sushi"]


# ---- graph flow -------------------------------------------------------------

def test_interest_signal_is_idempotent_and_reversible(graph):
    ana, bruno = [decay.add_person(graph, n) for n in ("Ana", "Bruno")]
    ev = discover.publish_event(graph, "Sushi night", start=_iso(2), city="Lisbon",
                                topic="sushi", visibility="public")["event_id"]
    assert discover.mark_interest(graph, ev, ana)["going_count"] == 1
    assert discover.mark_interest(graph, ev, ana)["going_count"] == 1     # idempotent
    assert discover.mark_interest(graph, ev, bruno)["going_count"] == 2
    assert discover.mark_interest(graph, ev, ana, going=False)["going_count"] == 1
    with pytest.raises(ValueError):
        discover.mark_interest(graph, "nope", ana)


def test_feed_spans_here_and_an_upcoming_trip(graph):
    ana = decay.add_person(graph, "Ana")
    here = discover.publish_event(graph, "Berlin bouldering", start=_iso(2), city="Berlin",
                                  topic="climbing", visibility="public")["event_id"]
    there = discover.publish_event(graph, "Lisbon sushi night", start=_iso(20), city="Lisbon",
                                   topic="sushi", visibility="public")["event_id"]
    discover.publish_event(graph, "Paris thing", start=_iso(3), city="Paris",
                           topic="sushi", visibility="public")
    for _ in range(3):
        discover.mark_interest(graph, here, decay.add_person(graph, f"p{_}"))
    discover.mark_interest(graph, there, ana)

    # a declared trip pulls its city into the same stream as where you are now
    discover.set_intent(graph, "Lisbon", ["sushi"],
                        starts=_iso(14)[:10], ends=_iso(28)[:10])
    result = discover.feed(graph, cities=["Berlin"], interests=["climbing", "sushi"])

    titles = [i["title"] for i in result["items"]]
    assert "Berlin bouldering" in titles and "Lisbon sushi night" in titles
    assert "Paris thing" not in titles                    # not where you are or going
    lisbon = next(i for i in result["items"] if i["title"] == "Lisbon sushi night")
    assert "while you're in Lisbon" in " | ".join(lisbon["reasons"])


def test_trip_window_excludes_events_outside_your_dates(graph):
    discover.publish_event(graph, "Sushi while there", start=_iso(20), city="Lisbon",
                           topic="sushi", visibility="public")
    discover.publish_event(graph, "Sushi after you leave", start=_iso(60), city="Lisbon",
                           topic="sushi", visibility="public")
    discover.set_intent(graph, "Lisbon", ["sushi"], starts=_iso(14)[:10], ends=_iso(28)[:10])

    titles = [i["title"] for i in discover.feed(graph)["items"]]
    assert titles == ["Sushi while there"]


def test_feed_uses_your_graph_profile_when_you_dont_say(graph):
    graph.session("t", {"*"}).create_entity("interest", {"name": "climbing"}, source="seed")
    discover.publish_event(graph, "Bouldering session", start=_iso(2), city="Lisbon",
                           topic="climbing", visibility="public")
    result = discover.feed(graph, cities=["Lisbon"])
    assert result["interests"] == ["climbing"]
    assert result["items"][0]["title"] == "Bouldering session"


# ---- gateway ----------------------------------------------------------------

def test_gateway_feed_journey(cfg):
    client = TestClient(create_app(cfg))
    ana = client.post("/v1/people", json={"name": "Ana"}).json()["person_id"]
    ev = client.post("/v1/discover/events", json={
        "title": "Sushi night at Bairro", "start": _iso(2), "city": "Lisbon",
        "topic": "sushi", "visibility": "public"}).json()["event_id"]
    client.post("/v1/discover/events", json={
        "title": "Pool evening", "start": _iso(2), "city": "Lisbon",
        "topic": "pool", "visibility": "private"})

    assert client.post("/v1/feed/interested", json={
        "event_id": ev, "person_id": ana}).json()["going_count"] == 1

    feed = client.get("/v1/feed", params={"cities": "Lisbon", "interests": "sushi"}).json()
    titles = [i["title"] for i in feed["items"]]
    assert titles == ["Sushi night at Bairro"]            # the private one never appears
    assert "1 interested" in " | ".join(feed["items"][0]["reasons"])
