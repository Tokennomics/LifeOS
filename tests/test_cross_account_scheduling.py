"""Cross-account scheduling: answering a crew session opened in someone else's account.

Membership already spans accounts. Scheduling did not: the coordination is an entity in
the organiser's graph, and the owner scope that keeps everything else private also stopped
a member from reading the session they were invited to plan. The participant grant is what
crosses that line — and nothing wider.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.coordinate import coordinator
from modules.crews import crews
from substrate.graph import Graph

PW = "correct-horse-battery"
FRI, SAT = "2026-08-07T19:00", "2026-08-08T19:00"


def _acct(graph, handle):
    a = accounts.register(graph, handle, PW)
    return Graph(graph.conn, graph.bus, default_owner=a["owner_id"]), a["account_id"]


@pytest.fixture
def world(graph):
    """Ana runs a Lisbon crew; Bruno and Cara joined it from their own accounts."""
    ana, ana_id = _acct(graph, "ana")
    bruno, bruno_id = _acct(graph, "bruno")
    cara, cara_id = _acct(graph, "cara")
    crew = crews.create(ana, "Lisbon Sushi Club", topic="sushi", city="Lisbon",
                        visibility="public", admission="open", admin_id=ana_id)["id"]
    crews.request_join(bruno, crew, bruno_id)
    crews.request_join(cara, crew, cara_id)
    return {"ana": ana, "bruno": bruno, "cara": cara, "crew": crew,
            "ana_id": ana_id, "bruno_id": bruno_id, "cara_id": cara_id}


def _open(w, quorum=2):
    return coordinator.propose_group(w["ana"], w["crew"], [FRI, SAT], ["Sushi Bar"],
                                     quorum=quorum)


# ---- the answer that used to be impossible ----------------------------------

def test_opening_a_session_makes_every_member_a_participant(world):
    out = _open(world)
    assert set(out["participants"]) == {world["ana_id"], world["bruno_id"], world["cara_id"]}


def test_a_member_in_another_account_can_answer(world):
    coord = _open(world)["coordination_id"]
    out = coordinator.respond_group(world["bruno"], coord, world["bruno_id"],
                                    {"slots": {SAT: 2}})
    assert out["responded"] == [world["bruno_id"]]
    # and he can read back the session he just answered
    assert coordinator.get(world["bruno"], coord, world["bruno_id"])["crew_name"] == "Lisbon Sushi Club"


def test_a_crew_night_gets_agreed_across_three_accounts(world):
    coord = _open(world)["coordination_id"]
    coordinator.respond_group(world["ana"], coord, world["ana_id"], {"slots": {FRI: 1, SAT: 2}})
    coordinator.respond_group(world["bruno"], coord, world["bruno_id"], {"slots": {SAT: 3}})
    out = coordinator.respond_group(world["cara"], coord, world["cara_id"], {"slots": {SAT: 1}})

    best = out["candidates"][0]
    assert best["slot"] == SAT and best["attendee_count"] == 3

    coordinator.approve_group(world["ana"], coord, world["ana_id"], 0)
    done = coordinator.approve_group(world["bruno"], coord, world["bruno_id"], 0)
    assert done["status"] == "confirmed"
    assert sorted(done["backers"]) == sorted([world["ana_id"], world["bruno_id"]])

    # Everyone sees the same outcome, whichever account they read it from
    for who, subject in (("ana", "ana_id"), ("bruno", "bruno_id"), ("cara", "cara_id")):
        seen = coordinator.get(world[who], coord, world[subject])
        assert seen["status"] == "confirmed"
        assert seen["confirmed"]["slot"] == SAT and seen["confirmed"]["place"] == "Sushi Bar"


def test_each_attendee_puts_the_night_on_their_own_calendar(world):
    """The confirmed meet is shared state; a calendar entry is a local materialisation.
    Nobody writes an event into somebody else's graph."""
    coord = _open(world)["coordination_id"]
    for who, subject in (("ana", "ana_id"), ("bruno", "bruno_id")):
        coordinator.respond_group(world[who], coord, world[subject], {"slots": {SAT: 1}})
    coordinator.approve_group(world["ana"], coord, world["ana_id"], 0)
    coordinator.approve_group(world["bruno"], coord, world["bruno_id"], 0)

    # Bruno tipped it over quorum, so the event landed in his graph already
    assert coordinator.add_to_calendar(world["bruno"], coord, world["bruno_id"])["added"] is False
    added = coordinator.add_to_calendar(world["ana"], coord, world["ana_id"])
    assert added["added"] is True
    ev = world["ana"].session("t", {"events:read"}).get_entity(added["event_id"])
    assert ev["attrs"]["start"] == SAT and ev["attrs"]["place"] == "Sushi Bar"
    # ...and asking twice doesn't duplicate the night
    assert coordinator.add_to_calendar(world["ana"], coord, world["ana_id"])["added"] is False

    # Cara never said she was coming, so there is nothing for her to add
    with pytest.raises(ValueError):
        coordinator.add_to_calendar(world["cara"], coord, world["cara_id"])


def test_a_participant_finds_their_sessions_without_being_handed_an_id(world):
    coord = _open(world)["coordination_id"]
    mine = coordinator.my_sessions(world["bruno"], world["bruno_id"])
    assert [c["id"] for c in mine] == [coord]
    assert mine[0]["quorum"] == 2


# ---- what the grant does NOT open up ----------------------------------------

def test_a_stranger_cannot_touch_the_session(world, graph):
    dave, dave_id = _acct(graph, "dave")
    coord = _open(world)["coordination_id"]

    with pytest.raises(ValueError):
        coordinator.get(dave, coord, dave_id)
    with pytest.raises(ValueError):
        coordinator.respond_group(dave, coord, dave_id, {"slots": {SAT: 1}})
    with pytest.raises(ValueError):
        coordinator.approve_group(dave, coord, dave_id, 0)
    assert coordinator.my_sessions(dave, dave_id) == []


def test_a_participant_grant_opens_nothing_but_the_session(world):
    """Bruno can plan Friday night. He still cannot see Ana's private life."""
    secret = world["ana"].session("seed", {"goals:write"}).create_entity(
        "goal", {"title": "Ana's private goal"}, source="seed")
    _open(world)
    assert world["bruno"].session("t", {"goals:read"}).get_entity(secret) is None
    assert crews.create(world["ana"], "Ana's Pool Crew", visibility="private",
                        admin_id=world["ana_id"])["id"]
    assert [c["name"] for c in crews.my_crews(world["bruno"], world["bruno_id"])] \
        == ["Lisbon Sushi Club"]


def test_leaving_the_crew_ends_the_invitation_to_plan(world):
    coord = _open(world)["coordination_id"]
    crews.leave(world["bruno"], world["crew"], world["bruno_id"])

    # The organiser's next touch re-derives participants from the crew, dropping him
    coordinator.respond_group(world["ana"], coord, world["ana_id"], {"slots": {SAT: 1}})
    with pytest.raises(ValueError):
        coordinator.respond_group(world["bruno"], coord, world["bruno_id"], {"slots": {SAT: 1}})


def test_a_forged_participant_grant_buys_nothing(world, graph):
    """A grant row needs only `content:write`, so the grant is how a member REACHES the
    session — the crew is the authority on whether they belong on it."""
    dave, dave_id = _acct(graph, "dave")
    coord = _open(world)["coordination_id"]
    dave.session("forge", {"content:write"}).grant(
        dave_id, coordinator.PARTICIPANT, coord, source="forge")

    with pytest.raises(ValueError, match="not a member"):
        coordinator.respond_group(dave, coord, dave_id, {"slots": {SAT: 1}})
    with pytest.raises(ValueError, match="not a member"):
        coordinator.approve_group(dave, coord, dave_id, 0)


def test_a_departed_members_availability_stops_counting(world):
    """Quorum is about who is actually coming. Someone who left the crew can't be the
    reason a night goes ahead, even though they answered while they were in it."""
    coord = _open(world)["coordination_id"]
    coordinator.respond_group(world["bruno"], coord, world["bruno_id"], {"slots": {SAT: 1}})
    out = coordinator.respond_group(world["cara"], coord, world["cara_id"], {"slots": {SAT: 1}})
    assert out["status"] == "awaiting_approval" and out["candidates"][0]["attendee_count"] == 2

    crews.leave(world["cara"], world["crew"], world["cara_id"])
    out = coordinator.respond_group(world["ana"], coord, world["ana_id"], {"slots": {FRI: 1}})
    assert out["status"] == "collecting" and out["candidates"] == []
    assert world["cara_id"] not in coordinator.get(world["ana"], coord, world["ana_id"])["responded"]


def test_someone_who_joins_late_can_still_answer(world, graph):
    """Membership moves while a session is open — Friday's plan should reach Tuesday's
    new member once the organiser next touches it."""
    coord = _open(world)["coordination_id"]
    eve, eve_id = _acct(graph, "eve")
    crews.request_join(eve, world["crew"], eve_id)

    coordinator.respond_group(world["ana"], coord, world["ana_id"], {"slots": {SAT: 1}})
    out = coordinator.respond_group(eve, coord, eve_id, {"slots": {SAT: 1}})
    assert eve_id in out["responded"]


def test_the_owner_still_cannot_answer_for_a_non_member(world, graph):
    coord = _open(world)["coordination_id"]
    stranger = world["ana"].session("seed", {"people:write"}).create_entity(
        "person", {"name": "Someone else"}, source="seed")
    with pytest.raises(ValueError):
        coordinator.respond_group(world["ana"], coord, stranger, {"slots": {SAT: 1}})


# ---- gateway ----------------------------------------------------------------

def test_gateway_group_session_across_two_signed_in_accounts(cfg):
    client = TestClient(create_app(cfg))
    for handle in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": handle, "password": PW})
    tok = {h: client.post("/v1/auth/login", json={"handle": h, "password": PW}).json()["token"]
           for h in ("ana", "bruno")}
    head = lambda h: {"Authorization": f"Bearer {tok[h]}"}
    ana_id = client.get("/v1/auth/me", headers=head("ana")).json()["account_id"]

    crew = client.post("/v1/crews", json={
        "name": "Lisbon Sushi Club", "city": "Lisbon", "visibility": "public",
        "admission": "open", "admin_id": ana_id}, headers=head("ana")).json()["id"]
    client.post("/v1/crews/request", json={"crew_id": crew}, headers=head("bruno"))

    coord = client.post("/v1/coordinate/group/propose", json={
        "crew_id": crew, "slots": [FRI, SAT], "places": ["Sushi Bar"], "quorum": 2},
        headers=head("ana")).json()["coordination_id"]

    # Bruno discovers the session from his side — no id passed to him out of band
    mine = client.get("/v1/coordinate/group/mine", headers=head("bruno")).json()["coordinations"]
    assert [c["id"] for c in mine] == [coord]

    for h in ("ana", "bruno"):
        r = client.post("/v1/coordinate/group/respond", json={
            "coordination_id": coord, "weights": {"slots": {SAT: 1}}}, headers=head(h))
        assert r.status_code == 200
    for h in ("ana", "bruno"):
        done = client.post("/v1/coordinate/group/approve", json={
            "coordination_id": coord, "choice": 0}, headers=head(h)).json()
    assert done["status"] == "confirmed"

    added = client.post("/v1/coordinate/group/calendar", json={"coordination_id": coord},
                        headers=head("ana")).json()
    assert added["added"] is True
