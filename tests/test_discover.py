"""Discover — admission policy + intent-driven local matching.

The scenario under test: you land in Lisbon wanting sushi night, and LifeOS surfaces the
public sushi event — while your invite-only pool evening stays invisible to everyone.
"""

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.crews import crews
from modules.discover import core, discover
from modules.reconnect import decay

SOON, LATER = "2099-08-01T20:00", "2099-08-05T20:00"
PAST = "2000-01-01T20:00"


# ---- pure matcher -----------------------------------------------------------

def _item(title, topic="", city="Lisbon", start=SOON, visibility="public", kind="event"):
    return {"id": title, "kind": kind, "title": title, "topic": topic,
            "city": city, "start": start, "visibility": visibility}


def test_private_items_never_surface_whatever_the_match():
    items = [_item("Sushi night", topic="sushi", visibility="private"),
             _item("Pool evening", topic="pool", visibility="private")]
    assert core.rank_matches(items, ["sushi", "pool"], city="Lisbon") == []


def test_interest_match_outranks_a_generic_event():
    items = [_item("Generic meetup", topic="social"), _item("Sushi night", topic="sushi")]
    out = core.rank_matches(items, ["sushi"], city="Lisbon")
    assert [i["title"] for i in out] == ["Sushi night", "Generic meetup"]
    assert out[0]["score"] > out[1]["score"] == 0.0


def test_city_filter_is_strict():
    items = [_item("Sushi night", topic="sushi", city="Porto")]
    assert core.rank_matches(items, ["sushi"], city="Lisbon") == []
    assert len(core.rank_matches(items, ["sushi"], city="Porto")) == 1


def test_past_events_are_dropped_and_soonest_breaks_ties():
    items = [_item("Sushi night", topic="sushi", start=PAST),
             _item("Sushi feast", topic="sushi", start=LATER),
             _item("Sushi pop-up", topic="sushi", start=SOON)]
    out = core.rank_matches(items, ["sushi"], city="Lisbon", now="2026-01-01T00:00")
    assert [i["title"] for i in out] == ["Sushi pop-up", "Sushi feast"]


def test_title_word_match_counts_not_substrings():
    # "sushi" in the title matches; "sus" must not match "sushi"
    items = [_item("Late sushi run", topic="food")]
    assert core.score_item(items[0], ["sushi"]) > 0
    assert core.score_item(items[0], ["sus"]) == 0
    assert core.score_item(items[0], []) == 0.0     # no interests, no signal


# ---- admission policy -------------------------------------------------------

def test_open_admission_joins_instantly(graph):
    owner, traveller = [decay.add_person(graph, n) for n in ("Owner", "Traveller")]
    crew = crews.create(graph, "Drop-in Climbing", city="Lisbon", visibility="public",
                        admission="open", admin_id=owner)["id"]
    r = crews.request_join(graph, crew, traveller)
    assert r["joined"] is True and r["requested"] is False
    assert traveller in crews.members(graph, crew)


def test_approval_admission_queues_for_an_admin(graph):
    owner, traveller = [decay.add_person(graph, n) for n in ("Owner", "Traveller")]
    crew = crews.create(graph, "Curated Climbing", city="Lisbon", visibility="public",
                        admission="approval", admin_id=owner)["id"]
    r = crews.request_join(graph, crew, traveller)
    assert r["requested"] is True and r["joined"] is False
    assert traveller not in crews.members(graph, crew)
    crews.approve_request(graph, crew, traveller, by=owner)
    assert traveller in crews.members(graph, crew)


def test_invite_admission_and_private_crews_refuse_requests(graph):
    owner, traveller = [decay.add_person(graph, n) for n in ("Owner", "Traveller")]
    listed_but_closed = crews.create(graph, "Listed Closed", city="Lisbon", visibility="public",
                                     admission="invite", admin_id=owner)["id"]
    private = crews.create(graph, "Pool Crew", city="Lisbon", visibility="private",
                           admission="open", admin_id=owner)["id"]
    with pytest.raises(ValueError):
        crews.request_join(graph, listed_but_closed, traveller)
    with pytest.raises(ValueError):
        crews.request_join(graph, private, traveller)      # private is invite-only regardless
    assert crews.get(graph, private)["admission"] == "invite"


def test_admin_can_change_policy(graph):
    owner, other = [decay.add_person(graph, n) for n in ("Owner", "Other")]
    crew = crews.create(graph, "Climbing", city="Lisbon", admin_id=owner)["id"]
    updated = crews.set_policy(graph, crew, visibility="public", admission="open", by=owner)
    assert updated["visibility"] == "public" and updated["admission"] == "open"
    with pytest.raises(ValueError):
        crews.set_policy(graph, crew, admission="open", by=other)      # not an admin
    with pytest.raises(ValueError):
        crews.set_policy(graph, crew, admission="whenever", by=owner)  # invalid


# ---- the scenario -----------------------------------------------------------

def test_lisbon_sushi_intent_finds_public_and_hides_private(graph):
    owner = decay.add_person(graph, "Owner")
    discover.publish_event(graph, "Sushi night at Bairro", start=SOON, city="Lisbon",
                           topic="sushi", visibility="public")
    discover.publish_event(graph, "Pool evening", start=SOON, city="Lisbon",
                           topic="pool", visibility="private")        # invite-only, mine
    discover.publish_event(graph, "Sushi night", start=SOON, city="Porto",
                           topic="sushi", visibility="public")        # wrong city
    crews.create(graph, "Lisbon Sushi Club", topic="sushi", city="Lisbon",
                 visibility="public", admission="open", admin_id=owner)
    crews.create(graph, "Pool Crew", topic="pool", city="Lisbon",
                 visibility="private", admin_id=owner)

    result = discover.find(graph, city="Lisbon", interests=["sushi"])
    assert [e["title"] for e in result["events"]] == ["Sushi night at Bairro"]
    assert [c["title"] for c in result["crews"]] == ["Lisbon Sushi Club"]

    # The private pool evening is invisible even to someone hunting for exactly it —
    # browse still shows what else is on locally, but nothing private ever appears.
    pool = discover.find(graph, city="Lisbon", interests=["pool"])
    titles = [i["title"] for i in pool["events"] + pool["crews"]]
    assert "Pool evening" not in titles and "Pool Crew" not in titles
    assert all(i["score"] == 0.0 for i in pool["events"] + pool["crews"])   # nothing matched

    # search mode returns only genuine matches
    strict = discover.find(graph, city="Lisbon", interests=["pool"], only_matches=True)
    assert strict["events"] == [] and strict["crews"] == []


def test_find_falls_back_to_the_graphs_own_interests(graph):
    s = graph.session("t", {"*"})
    s.create_entity("interest", {"name": "climbing"}, source="seed")
    discover.publish_event(graph, "Bouldering session", start=SOON, city="Lisbon",
                           topic="climbing", visibility="public")
    discover.publish_event(graph, "Knitting circle", start=SOON, city="Lisbon",
                           topic="knitting", visibility="public")

    result = discover.find(graph, city="Lisbon")          # no interests passed
    assert result["interests"] == ["climbing"]
    assert result["events"][0]["title"] == "Bouldering session"
    assert result["events"][0]["score"] > result["events"][1]["score"]


def test_intent_is_stored_and_matchable(graph):
    discover.publish_event(graph, "Sushi night", start=SOON, city="Lisbon",
                           topic="sushi", visibility="public")
    intent = discover.set_intent(graph, "Lisbon", ["sushi"], starts="2099-07-30", ends="2099-08-10")
    assert discover.intents(graph)[0]["city"] == "Lisbon"

    matched = discover.find_for_intent(graph, intent["intent_id"])
    assert matched["intent_id"] == intent["intent_id"]
    assert [e["title"] for e in matched["events"]] == ["Sushi night"]

    with pytest.raises(ValueError):
        discover.set_intent(graph, "")                     # a city is required
    with pytest.raises(ValueError):
        discover.find_for_intent(graph, "nope")


def test_publish_validates(graph):
    with pytest.raises(ValueError):
        discover.publish_event(graph, "   ")
    with pytest.raises(ValueError):
        discover.publish_event(graph, "X", visibility="semi-public")


# ---- gateway ----------------------------------------------------------------

def test_gateway_discover_journey(cfg):
    client = TestClient(create_app(cfg))
    owner = client.post("/v1/people", json={"name": "Owner"}).json()["person_id"]
    client.post("/v1/discover/events", json={
        "title": "Sushi night at Bairro", "start": SOON, "city": "Lisbon",
        "topic": "sushi", "visibility": "public"})
    client.post("/v1/discover/events", json={
        "title": "Pool evening", "start": SOON, "city": "Lisbon",
        "topic": "pool", "visibility": "private"})
    client.post("/v1/crews", json={"name": "Lisbon Sushi Club", "topic": "sushi", "city": "Lisbon",
                                   "visibility": "public", "admission": "open", "admin_id": owner})

    found = client.get("/v1/discover", params={"city": "Lisbon", "interests": "sushi"}).json()
    assert [e["title"] for e in found["events"]] == ["Sushi night at Bairro"]
    assert [c["title"] for c in found["crews"]] == ["Lisbon Sushi Club"]

    # a drop-in crew admits instantly through the API
    traveller = client.post("/v1/people", json={"name": "Traveller"}).json()["person_id"]
    joined = client.post("/v1/crews/request", json={
        "crew_id": found["crews"][0]["id"], "person_id": traveller}).json()
    assert joined["joined"] is True

    intent = client.post("/v1/discover/intents", json={
        "city": "Lisbon", "interests": ["sushi"]}).json()
    by_intent = client.get(f"/v1/discover/intents/{intent['intent_id']}").json()
    assert [e["title"] for e in by_intent["events"]] == ["Sushi night at Bairro"]
