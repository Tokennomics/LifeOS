"""Crews + group coordination (the crew generalization of Phase 3)."""

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.coordinate import coordinator, core
from modules.crews import crews
from modules.reconnect import decay

FRI, SAT, SUN = "2026-08-07T19:00", "2026-08-08T19:00", "2026-08-09T19:00"


def _people(graph, *names):
    return [decay.add_person(graph, n) for n in names]


# ---- crew model -------------------------------------------------------------

def test_create_browse_and_join(graph):
    a, b, c = _people(graph, "Ana", "Bruno", "Cara")
    crew = crews.create(graph, "Lisbon Climbing", topic="climbing", city="Lisbon", member_ids=[a, b])
    assert crew["member_count"] == 2 and crew["city"] == "Lisbon"

    joined = crews.join(graph, crew["id"], c)
    assert joined["added"] is True and joined["member_count"] == 3
    assert crews.join(graph, crew["id"], c)["added"] is False       # idempotent
    assert set(crews.members(graph, crew["id"])) == {a, b, c}


def test_browse_filters_by_topic_and_city(graph):
    crews.create(graph, "Lisbon Climbing", topic="climbing", city="Lisbon")
    crews.create(graph, "Lisbon Running", topic="running", city="Lisbon")
    crews.create(graph, "Berlin Climbing", topic="climbing", city="Berlin")

    assert len(crews.browse(graph)) == 3
    assert [c["name"] for c in crews.browse(graph, city="lisbon")] == ["Lisbon Climbing", "Lisbon Running"]
    assert [c["name"] for c in crews.browse(graph, topic="CLIMBING", city="Berlin")] == ["Berlin Climbing"]


def test_duplicate_crew_name_rejected(graph):
    crews.create(graph, "Lisbon Climbing", topic="climbing", city="Lisbon")
    with pytest.raises(ValueError):
        crews.create(graph, "lisbon climbing")     # case-insensitive clash
    with pytest.raises(ValueError):
        crews.create(graph, "   ")                 # needs a name


# ---- group ranking engine ---------------------------------------------------

def test_group_ranking_prefers_the_night_more_people_can_make():
    proposal = {"slots": [FRI, SAT], "places": ["Gym"]}
    weights = {
        "a": {"slots": {FRI: 3, SAT: 1}},     # Ana strongly prefers Friday
        "b": {"slots": {SAT: 1}},
        "c": {"slots": {SAT: 1}},
    }
    out = core.rank_group_candidates(proposal, weights, quorum=2)
    # Saturday has 3 attendees vs Friday's 1 -> attendance beats Ana's preference
    assert out[0]["slot"] == SAT and out[0]["attendee_count"] == 3
    assert [c["slot"] for c in out] == [SAT]      # Friday fails quorum of 2


def test_group_quorum_filters_thin_nights():
    proposal = {"slots": [FRI, SAT], "places": ["Gym"]}
    weights = {"a": {"slots": {FRI: 1, SAT: 1}}, "b": {"slots": {SAT: 1}}}
    assert [c["slot"] for c in core.rank_group_candidates(proposal, weights, quorum=2)] == [SAT]
    assert core.rank_group_candidates(proposal, weights, quorum=3) == []


def test_place_veto_only_counts_from_that_slots_attendees():
    proposal = {"slots": [FRI], "places": ["Gym", "Pub"]}
    weights = {
        "a": {"slots": {FRI: 1}, "places": {"Gym": 1, "Pub": 1}},
        "b": {"slots": {FRI: 1}, "places": {"Gym": 1, "Pub": 1}},
        "c": {"slots": {}, "places": {"Gym": 0}},   # can't come Friday; his veto must not bind
    }
    out = core.rank_group_candidates(proposal, weights, quorum=2)
    assert out[0]["place"] == "Gym" and out[0]["attendees"] == ["a", "b"]


# ---- group flow -------------------------------------------------------------

def test_group_flow_confirms_at_quorum_and_links_attendees(graph):
    a, b, c = _people(graph, "Ana", "Bruno", "Cara")
    crew = crews.create(graph, "Lisbon Climbing", topic="climbing", city="Lisbon",
                        member_ids=[a, b, c])
    prop = coordinator.propose_group(graph, crew["id"], [FRI, SAT], ["Gym", "Pub"], quorum=2)
    cid = prop["coordination_id"]
    assert prop["status"] == "collecting" and "Lisbon Climbing" in prop["ask"]

    coordinator.respond_group(graph, cid, a, {"slots": {SAT: 1}, "places": {"Gym": 2, "Pub": 1}})
    r = coordinator.respond_group(graph, cid, b, {"slots": {SAT: 1}, "places": {"Gym": 1}})
    assert r["status"] == "awaiting_approval"
    assert r["candidates"][0]["slot"] == SAT and r["candidates"][0]["place"] == "Gym"

    first = coordinator.approve_group(graph, cid, a, 0)
    assert first["status"] == "awaiting_approval"          # one backer, quorum 2
    done = coordinator.approve_group(graph, cid, b, 0)
    assert done["status"] == "confirmed" and sorted(done["backers"]) == sorted([a, b])

    s = graph.session("coordinate", coordinator.SCOPES)
    ev = s.get_entity(done["event_id"])
    assert ev["attrs"]["start"] == SAT and ev["attrs"]["place"] == "Gym" and ev["attrs"]["busy"] is True
    linked = {p["id"] for p in s.neighbors(ev["id"], rel="with", direction="out")}
    assert linked == {a, b}                                 # only the people actually coming


def test_non_member_cannot_respond_and_unavailable_cannot_approve(graph):
    a, b, outsider = _people(graph, "Ana", "Bruno", "Zed")
    crew = crews.create(graph, "Lisbon Climbing", member_ids=[a, b])
    cid = coordinator.propose_group(graph, crew["id"], [FRI, SAT], ["Gym"])["coordination_id"]

    with pytest.raises(ValueError):
        coordinator.respond_group(graph, cid, outsider, {"slots": {SAT: 1}})

    coordinator.respond_group(graph, cid, a, {"slots": {SAT: 1}})
    coordinator.respond_group(graph, cid, b, {"slots": {SAT: 1}})
    # Ana never said she was free FRI; she can't approve a candidate she can't attend
    with pytest.raises(ValueError):
        coordinator.approve_group(graph, cid, a, 99)


def test_group_needs_a_real_crew_and_sane_quorum(graph):
    a, b = _people(graph, "Ana", "Bruno")
    crew = crews.create(graph, "Crew", member_ids=[a, b])
    with pytest.raises(ValueError):
        coordinator.propose_group(graph, "nope", [FRI], ["Gym"])
    with pytest.raises(ValueError):
        coordinator.propose_group(graph, crew["id"], [FRI], ["Gym"], quorum=1)


# ---- gateway ----------------------------------------------------------------

def test_gateway_crew_and_group_roundtrip(cfg):
    client = TestClient(create_app(cfg))
    a = client.post("/v1/people", json={"name": "Ana"}).json()["person_id"]
    b = client.post("/v1/people", json={"name": "Bruno"}).json()["person_id"]
    crew = client.post("/v1/crews", json={
        "name": "Lisbon Climbing", "topic": "climbing", "city": "Lisbon", "member_ids": [a, b]}).json()

    found = client.get("/v1/crews", params={"topic": "climbing", "city": "Lisbon"}).json()["crews"]
    assert found[0]["name"] == "Lisbon Climbing" and found[0]["member_count"] == 2

    cid = client.post("/v1/coordinate/group/propose", json={
        "crew_id": crew["id"], "slots": [FRI, SAT], "places": ["Gym"], "quorum": 2,
    }).json()["coordination_id"]
    client.post("/v1/coordinate/group/respond",
                json={"coordination_id": cid, "person_id": a, "weights": {"slots": {SAT: 1}}})
    resp = client.post("/v1/coordinate/group/respond",
                       json={"coordination_id": cid, "person_id": b, "weights": {"slots": {SAT: 1}}}).json()
    assert resp["status"] == "awaiting_approval"

    client.post("/v1/coordinate/group/approve", json={"coordination_id": cid, "person_id": a, "choice": 0})
    done = client.post("/v1/coordinate/group/approve",
                       json={"coordination_id": cid, "person_id": b, "choice": 0}).json()
    assert done["status"] == "confirmed" and done["event_id"]
