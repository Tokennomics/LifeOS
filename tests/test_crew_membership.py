"""Crew membership lifecycle, visibility, and the safety rails that gate discovery."""

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.coordinate import coordinator
from modules.crews import crews
from modules.reconnect import decay


def _people(graph, *names):
    return [decay.add_person(graph, n) for n in names]


# ---- substrate: revocation --------------------------------------------------

def test_revoke_removes_a_grant_and_is_idempotent(graph):
    s = graph.session("t", {"*"})
    person = s.create_entity("person", {"name": "A"}, source="t")
    space = s.create_entity("content", {"type": "crew"}, source="t")
    s.grant(person, "crew:member", space, source="t")
    assert [g["scope"] for g in s.grants_for(space)] == ["crew:member"]
    assert s.revoke(person, "crew:member", space, source="t") == 1
    assert s.grants_for(space) == []
    assert s.revoke(person, "crew:member", space, source="t") == 0   # no-op, no error


# ---- invite flow (private crews) --------------------------------------------

def test_invite_accept_and_decline(graph):
    owner, ana, bruno = _people(graph, "Owner", "Ana", "Bruno")
    crew = crews.create(graph, "Climbers", admin_id=owner)["id"]

    crews.invite(graph, crew, ana, by=owner)
    crews.invite(graph, crew, bruno, by=owner)
    assert {p["name"] for p in crews.get(graph, crew)["invited"]} == {"Ana", "Bruno"}

    crews.accept_invite(graph, crew, ana)
    crews.decline_invite(graph, crew, bruno)
    view = crews.get(graph, crew)
    assert {p["name"] for p in view["members"]} == {"Owner", "Ana"}   # admin counts as member
    assert view["invited"] == []
    with pytest.raises(ValueError):
        crews.accept_invite(graph, crew, bruno)      # invite is gone after declining


def test_only_admins_can_invite_when_an_admin_exists(graph):
    owner, ana, zed = _people(graph, "Owner", "Ana", "Zed")
    crew = crews.create(graph, "Climbers", admin_id=owner, member_ids=[ana])["id"]
    with pytest.raises(ValueError):
        crews.invite(graph, crew, zed, by=ana)       # Ana is a member, not an admin
    crews.invite(graph, crew, zed, by=owner)         # admin can


def test_crew_without_admin_stays_open_to_its_members(graph):
    ana, bruno = _people(graph, "Ana", "Bruno")
    crew = crews.create(graph, "Mates", member_ids=[ana])["id"]   # no admin — personal crew
    crews.invite(graph, crew, bruno, by=ana)                      # not locked out
    assert [p["name"] for p in crews.get(graph, crew)["invited"]] == ["Bruno"]


# ---- public crews: request / approve ----------------------------------------

def test_public_crew_request_and_approval(graph):
    owner, traveller = _people(graph, "Owner", "Traveller")
    crew = crews.create(graph, "Lisbon Climbing", topic="climbing", city="Lisbon",
                        visibility="public", admin_id=owner)["id"]
    crews.request_join(graph, crew, traveller)
    assert [p["name"] for p in crews.get(graph, crew)["requested"]] == ["Traveller"]

    crews.approve_request(graph, crew, traveller, by=owner)
    assert {p["name"] for p in crews.get(graph, crew)["members"]} == {"Owner", "Traveller"}


def test_private_crews_cannot_be_requested(graph):
    owner, traveller = _people(graph, "Owner", "Traveller")
    crew = crews.create(graph, "Inner Circle", visibility="private", admin_id=owner)["id"]
    with pytest.raises(ValueError):
        crews.request_join(graph, crew, traveller)


def test_denied_request_clears(graph):
    owner, zed = _people(graph, "Owner", "Zed")
    crew = crews.create(graph, "Open Crew", visibility="public", admin_id=owner)["id"]
    crews.request_join(graph, crew, zed)
    crews.deny_request(graph, crew, zed, by=owner)
    assert crews.get(graph, crew)["requested"] == []
    assert zed not in crews.members(graph, crew)


# ---- directory visibility ---------------------------------------------------

def test_directory_query_only_lists_public_crews(graph):
    owner, = _people(graph, "Owner")
    crews.create(graph, "Lisbon Climbing", topic="climbing", city="Lisbon",
                 visibility="public", admin_id=owner)
    crews.create(graph, "Secret Supper", topic="food", city="Lisbon",
                 visibility="private", admin_id=owner)

    public = crews.browse(graph, city="Lisbon", visibility="public")
    assert [c["name"] for c in public] == ["Lisbon Climbing"]     # private one is invisible
    assert len(crews.browse(graph, city="Lisbon")) == 2           # owner's local view sees both


def test_my_crews_lists_only_where_you_belong(graph):
    ana, bruno = _people(graph, "Ana", "Bruno")
    crews.create(graph, "Ana's Crew", member_ids=[ana])
    crews.create(graph, "Bruno's Crew", member_ids=[bruno])
    assert [c["name"] for c in crews.my_crews(graph, ana)] == ["Ana's Crew"]


# ---- safety -----------------------------------------------------------------

def test_leaving_is_always_allowed(graph):
    owner, ana = _people(graph, "Owner", "Ana")
    crew = crews.create(graph, "Climbers", admin_id=owner, member_ids=[ana])["id"]
    crews.leave(graph, crew, ana)
    assert ana not in crews.members(graph, crew)
    with pytest.raises(ValueError):
        crews.leave(graph, crew, ana)     # already gone


def test_blocked_person_is_removed_and_cannot_return(graph):
    owner, zed = _people(graph, "Owner", "Zed")
    crew = crews.create(graph, "Lisbon Climbing", visibility="public", admin_id=owner,
                        member_ids=[zed])["id"]
    crews.block(graph, crew, zed, by=owner)

    assert zed not in crews.members(graph, crew)
    assert crews.is_blocked(graph, crew, zed) is True
    with pytest.raises(ValueError):
        crews.request_join(graph, crew, zed)          # can't request back in
    with pytest.raises(ValueError):
        crews.invite(graph, crew, zed, by=owner)      # can't be invited back in
    with pytest.raises(ValueError):
        crews.join(graph, crew, zed)                  # can't be added directly

    crews.unblock(graph, crew, zed, by=owner)
    crews.request_join(graph, crew, zed)              # allowed again after unblock


def test_blocked_member_drops_out_of_group_coordination(graph):
    owner, ana, zed = _people(graph, "Owner", "Ana", "Zed")
    crew = crews.create(graph, "Climbers", admin_id=owner, member_ids=[ana, zed])["id"]
    cid = coordinator.propose_group(graph, crew, ["Fri 19:00"], ["Gym"])["coordination_id"]
    coordinator.respond_group(graph, cid, zed, {"slots": {"Fri 19:00": 1}})

    crews.block(graph, crew, zed, by=owner)
    with pytest.raises(ValueError):
        coordinator.respond_group(graph, cid, zed, {"slots": {"Fri 19:00": 1}})


def test_reports_are_auditable_and_resolvable(graph):
    owner, reporter, zed = _people(graph, "Owner", "Reporter", "Zed")
    crew = crews.create(graph, "Lisbon Climbing", visibility="public", admin_id=owner,
                        member_ids=[reporter, zed])["id"]
    rep = crews.report(graph, crew, reporter, "Zed was abusive in the group chat", subject_id=zed)
    assert rep["status"] == "open"

    open_reports = crews.reports(graph, crew_id=crew, status="open")
    assert len(open_reports) == 1 and open_reports[0]["subject_id"] == zed

    crews.resolve_report(graph, rep["report_id"], "actioned")
    assert crews.reports(graph, crew_id=crew, status="open") == []
    with pytest.raises(ValueError):
        crews.report(graph, crew, reporter, "   ")          # a report needs a reason


# ---- gateway ----------------------------------------------------------------

def test_gateway_public_crew_journey(cfg):
    client = TestClient(create_app(cfg))
    owner = client.post("/v1/people", json={"name": "Owner"}).json()["person_id"]
    traveller = client.post("/v1/people", json={"name": "Traveller"}).json()["person_id"]

    crew = client.post("/v1/crews", json={
        "name": "Lisbon Climbing", "topic": "climbing", "city": "Lisbon",
        "visibility": "public", "admin_id": owner}).json()
    client.post("/v1/crews", json={"name": "Secret Supper", "city": "Lisbon", "admin_id": owner})

    # the directory only exposes public crews
    listed = client.get("/v1/crews", params={"city": "Lisbon", "visibility": "public"}).json()["crews"]
    assert [c["name"] for c in listed] == ["Lisbon Climbing"]

    client.post("/v1/crews/request", json={"crew_id": crew["id"], "person_id": traveller})
    approved = client.post("/v1/crews/request/approve", json={
        "crew_id": crew["id"], "person_id": traveller, "by": owner}).json()
    assert approved["member_count"] == 2

    # report -> moderation queue -> resolve
    rid = client.post("/v1/crews/report", json={
        "crew_id": crew["id"], "reporter_id": owner, "reason": "spam", "subject_id": traveller,
    }).json()["report_id"]
    assert len(client.get("/v1/crews/reports/open", params={"status": "open"}).json()["reports"]) == 1
    client.post("/v1/crews/report/resolve", json={"report_id": rid, "action": "actioned"})
    assert client.get("/v1/crews/reports/open", params={"status": "open"}).json()["reports"] == []

    # block removes them and the leave door is always open
    client.post("/v1/crews/block", json={"crew_id": crew["id"], "person_id": traveller, "by": owner})
    assert client.get(f"/v1/crews/{crew['id']}").json()["member_count"] == 1
