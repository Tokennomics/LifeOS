"""Coordinate — mediator-brokered 1:1 reconnect scheduling (roadmap Phase 3)."""

from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.coordinate import core, coordinator
from modules.reconnect import decay

S1, S2, S3 = "2026-08-01T18:00", "2026-08-02T18:00", "2026-08-03T18:00"


# ---- pure engine ------------------------------------------------------------

def test_engine_returns_the_common_slot():
    proposal = {"slots": [S1, S2, S3], "places": ["Cafe", "Park"]}
    a = {"slots": {S1: 1, S2: 1}, "places": {"Cafe": 1, "Park": 1}}
    b = {"slots": {S2: 1, S3: 1}, "places": {"Cafe": 1, "Park": 1}}
    out = core.rank_candidates(proposal, a, b)
    assert [c["slot"] for c in out] == [S2]          # only S2 is free for both
    assert out[0]["place"] == "Cafe"                 # tie on place -> alphabetical


def test_engine_orders_by_combined_preference():
    proposal = {"slots": [S1, S2], "places": ["Cafe"]}
    a = {"slots": {S1: 1, S2: 3}, "places": {}}
    b = {"slots": {S1: 1, S2: 1}, "places": {}}
    out = core.rank_candidates(proposal, a, b)
    assert [c["slot"] for c in out] == [S2, S1]      # S2 preferred by A -> ranks first


def test_engine_no_overlap_or_vetoed_place_yields_nothing():
    proposal = {"slots": [S1, S2], "places": ["Park"]}
    assert core.rank_candidates(proposal, {"slots": {S1: 1}}, {"slots": {S2: 1}}) == []  # no shared time
    # shared time but the peer vetoes the only place
    a = {"slots": {S1: 1}, "places": {"Park": 1}}
    b = {"slots": {S1: 1}, "places": {"Park": 0}}
    assert core.rank_candidates(proposal, a, b) == []


# ---- graph-backed flow ------------------------------------------------------

def test_full_flow_confirms_and_writes_the_meet(graph):
    sam = decay.add_person(graph, "Sam")
    p = coordinator.propose(graph, sam, [S1, S2], ["Cafe", "Park"],
                            {"slots": {S1: 1, S2: 2}, "places": {"Cafe": 1, "Park": 1}})
    assert p["status"] == "awaiting_peer" and "Sam" in p["ask"]
    cid = p["coordination_id"]

    r = coordinator.respond(graph, cid, {"slots": {S2: 1}, "places": {"Cafe": 1, "Park": 0}})
    assert r["status"] == "awaiting_approval"
    assert len(r["candidates"]) == 1 and r["candidates"][0]["slot"] == S2 and r["candidates"][0]["place"] == "Cafe"

    assert coordinator.approve(graph, cid, "owner", 0)["status"] == "awaiting_approval"  # one side only
    done = coordinator.approve(graph, cid, "peer", 0)
    assert done["status"] == "confirmed"

    # the meet is written as a busy event `with` the person
    s = graph.session("coordinate", coordinator.SCOPES)
    ev = s.get_entity(done["event_id"])
    assert ev["attrs"]["type"] == "meet" and ev["attrs"]["start"] == S2 and ev["attrs"]["place"] == "Cafe"
    assert ev["attrs"]["busy"] is True
    assert s.neighbors(ev["id"], rel="with", direction="out")[0]["id"] == sam


def test_mismatched_approvals_do_not_confirm(graph):
    sam = decay.add_person(graph, "Sam")
    cid = coordinator.propose(graph, sam, [S1, S2], ["Cafe"],
                              {"slots": {S1: 1, S2: 1}})["coordination_id"]
    coordinator.respond(graph, cid, {"slots": {S1: 1, S2: 1}})  # two candidates
    coordinator.approve(graph, cid, "owner", 0)
    still = coordinator.approve(graph, cid, "peer", 1)          # different pick
    assert still["status"] == "awaiting_approval"
    assert coordinator.get(graph, cid)["event_id"] is None


def test_peer_input_is_sanitized_to_proposed_keys(graph):
    sam = decay.add_person(graph, "Sam")
    cid = coordinator.propose(graph, sam, [S1], ["Cafe"], {"slots": {S1: 1}})["coordination_id"]
    # peer submits junk: an unproposed slot, an injected key, a huge weight
    r = coordinator.respond(graph, cid, {
        "slots": {S1: 999, "2099-01-01T00:00": 5, "__proto__": 1},
        "places": {"Cafe": 1, "Somewhere else": 5},
    })
    assert len(r["candidates"]) == 1 and r["candidates"][0]["slot"] == S1
    # only proposed keys survive, weights clamped
    peer = coordinator.get(graph, cid)
    saved = graph.session("coordinate", coordinator.SCOPES).get_entity(cid)["attrs"]["weights"]["peer"]
    assert set(saved["slots"]) == {S1} and saved["slots"][S1] == 10.0   # clamped from 999
    assert set(saved["places"]) == {"Cafe"}


def test_unknown_person_rejected(graph):
    import pytest
    with pytest.raises(ValueError):
        coordinator.propose(graph, "nope", [S1], ["Cafe"])


# ---- gateway roundtrip ------------------------------------------------------

def test_gateway_coordinate_roundtrip(cfg):
    client = TestClient(create_app(cfg))
    sam = client.post("/v1/people", json={"name": "Sam"}).json()["person_id"]
    prop = client.post("/v1/coordinate/propose", json={
        "person_id": sam, "slots": [S1, S2], "places": ["Cafe"],
        "weights": {"slots": {S1: 1, S2: 1}},
    }).json()
    cid = prop["coordination_id"]
    resp = client.post("/v1/coordinate/respond", json={
        "coordination_id": cid, "weights": {"slots": {S2: 1}}}).json()
    assert resp["status"] == "awaiting_approval" and resp["candidates"][0]["slot"] == S2
    client.post("/v1/coordinate/approve", json={"coordination_id": cid, "side": "owner", "choice": 0})
    done = client.post("/v1/coordinate/approve", json={"coordination_id": cid, "side": "peer", "choice": 0}).json()
    assert done["status"] == "confirmed" and done["event_id"]
    assert client.get("/v1/coordinate").json()["coordinations"][0]["status"] == "confirmed"
