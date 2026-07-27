"""Crew invite links — the growth loop, and the capability discipline it has to keep.

A share link is the one mechanic that works before there is any density: paste it into a
group chat that already exists and the group becomes a crew. That also makes it the most
dangerous thing in the crews module, because a link is a secret anyone can forward — so
most of what follows is about the bounds, not the happy path.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.crews import crews, invites
from substrate.graph import Graph

PW = "correct-horse-battery"


def _acct(graph, handle):
    a = accounts.register(graph, handle, PW)
    return Graph(graph.conn, graph.bus, default_owner=a["owner_id"]), a["account_id"]


@pytest.fixture
def world(graph):
    ana, ana_id = _acct(graph, "ana")
    bruno, bruno_id = _acct(graph, "bruno")
    crew = crews.create(ana, "Lisbon Sushi Club", city="Lisbon", visibility="public",
                        admission="approval", admin_id=ana_id)["id"]
    return {"graph": graph, "ana": ana, "bruno": bruno, "crew": crew,
            "ana_id": ana_id, "bruno_id": bruno_id}


# ---- the loop ---------------------------------------------------------------

def test_a_link_gets_a_stranger_into_a_crew_they_never_searched_for(world):
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    out = invites.redeem(world["bruno"], link["token"], world["bruno_id"])

    assert out["joined"] is True
    assert {m["name"] for m in crews.get(world["ana"], world["crew"])["members"]} == {"ana", "bruno"}


def test_a_link_works_for_a_private_crew_that_could_never_be_found(world):
    """The whole point of importing an existing group: it was never listed anywhere."""
    ana = world["ana"]
    crew = crews.create(ana, "Thursday Pool Crew", visibility="private",
                        admin_id=world["ana_id"])["id"]
    with pytest.raises(ValueError):                       # invisible by every other route
        crews.get(world["bruno"], crew)

    link = invites.create(ana, crew, by=world["ana_id"])
    assert invites.redeem(world["bruno"], link["token"], world["bruno_id"])["joined"] is True
    assert world["bruno_id"] in crews.members(ana, crew)


def test_a_link_beats_the_admission_policy_because_an_admin_issued_it(world):
    """The crew is request-then-approve, but a link IS the admin's approval, in advance."""
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    assert invites.redeem(world["bruno"], link["token"], world["bruno_id"])["joined"] is True
    assert crews.get(world["ana"], world["crew"])["requested"] == []      # no queue involved


def test_redeeming_twice_is_idempotent_and_doesnt_burn_a_use(world):
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"], max_uses=2)
    invites.redeem(world["bruno"], link["token"], world["bruno_id"])
    again = invites.redeem(world["bruno"], link["token"], world["bruno_id"])

    assert again["joined"] is False and again["already"] is True
    assert invites.for_crew(world["ana"], world["crew"], by=world["ana_id"])[0]["uses"] == 1


# ---- the bounds -------------------------------------------------------------

def test_the_token_is_shown_once_and_never_stored(world):
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    listed = invites.for_crew(world["ana"], world["crew"], by=world["ana_id"])[0]

    assert "token" not in listed and "token_hash" not in listed
    # and the stored record cannot reconstruct a working link
    stored = invites._sys(world["graph"]).get_entity(link["invite_id"])["attrs"]
    assert link["token"] not in str(stored)
    assert stored["token_hash"] == invites._hash_token(link["token"])


def test_a_used_up_link_stops_working(world, graph):
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"], max_uses=1)
    invites.redeem(world["bruno"], link["token"], world["bruno_id"])

    cara, cara_id = _acct(graph, "cara")
    with pytest.raises(ValueError, match="isn't valid"):
        invites.redeem(cara, link["token"], cara_id)


def test_an_expired_link_stops_working(world):
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    past = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1)).isoformat()
    invites._sys(world["graph"]).update_entity(
        link["invite_id"], {"expires_at": past}, source="test")

    with pytest.raises(ValueError, match="isn't valid"):
        invites.redeem(world["bruno"], link["token"], world["bruno_id"])


def test_a_link_can_be_revoked_immediately(world):
    """A shared secret you cannot withdraw is not a capability, it's a leak."""
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    invites.revoke(world["ana"], link["invite_id"], by=world["ana_id"])

    with pytest.raises(ValueError, match="isn't valid"):
        invites.redeem(world["bruno"], link["token"], world["bruno_id"])
    assert invites.for_crew(world["ana"], world["crew"], by=world["ana_id"])[0]["active"] is False


def test_a_block_outranks_an_invite(world):
    """The obvious hole in any share-link design: someone barred walking back in."""
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    crews.block(world["ana"], world["crew"], world["bruno_id"], by=world["ana_id"])

    with pytest.raises(ValueError, match="isn't valid"):
        invites.redeem(world["bruno"], link["token"], world["bruno_id"])
    assert world["bruno_id"] not in crews.members(world["ana"], world["crew"])


def test_a_link_never_confers_admin(world):
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    invites.redeem(world["bruno"], link["token"], world["bruno_id"])

    assert crews._state_of(world["bruno"].session("t", crews.SCOPES),
                           world["crew"], world["bruno_id"]) == crews.MEMBER
    with pytest.raises(ValueError):                  # still can't act as one
        invites.create(world["bruno"], world["crew"], by=world["bruno_id"])
    with pytest.raises(ValueError):
        crews.block(world["bruno"], world["crew"], world["ana_id"], by=world["bruno_id"])


def test_a_member_can_see_the_private_crew_they_joined(world):
    """Found by simulation, not by the tests. Links made private cross-account crews
    possible for the first time, and the READ path hadn't caught up: the crew is in nobody's
    public listing and not in the joiner's graph, so a member couldn't see the very group
    they'd just joined. Membership itself has to confer read access."""
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Thursday Pool Crew", visibility="private",
                        admin_id=world["ana_id"])["id"]
    link = invites.create(ana, crew, by=world["ana_id"])
    invites.redeem(bruno, link["token"], world["bruno_id"])

    assert [c["name"] for c in crews.my_crews(bruno, world["bruno_id"])] == ["Thursday Pool Crew"]
    assert crews.get(bruno, crew, world["bruno_id"])["member_count"] == 2
    # ...and it stays unlisted — being in it is not the same as publishing it
    assert crew not in {c["id"] for c in crews.directory(bruno)}
    crews.leave(bruno, crew, world["bruno_id"])
    with pytest.raises(ValueError):
        crews.get(bruno, crew, world["bruno_id"])


def test_a_private_crew_assembled_by_link_can_schedule_itself(world, graph):
    """The end of the loop: import a group chat, then actually plan something with it."""
    from modules.coordinate import coordinator

    ana, bruno = world["ana"], world["bruno"]
    cara, cara_id = _acct(graph, "cara")
    crew = crews.create(ana, "Thursday Pool Crew", visibility="private",
                        admin_id=world["ana_id"])["id"]
    link = invites.create(ana, crew, by=world["ana_id"])
    invites.redeem(bruno, link["token"], world["bruno_id"])
    invites.redeem(cara, link["token"], cara_id)

    fri = "2026-08-07T20:00"
    session = coordinator.propose_group(ana, crew, [fri], ["The Hall"], quorum=2)
    cid = session["coordination_id"]
    assert set(session["participants"]) == {world["ana_id"], world["bruno_id"], cara_id}

    coordinator.respond_group(bruno, cid, world["bruno_id"], {"slots": {fri: 1}})
    coordinator.respond_group(cara, cid, cara_id, {"slots": {fri: 1}})
    coordinator.approve_group(bruno, cid, world["bruno_id"], 0)
    done = coordinator.approve_group(cara, cid, cara_id, 0)
    assert done["status"] == "confirmed" and done["meet"]["slot"] == fri


def test_a_member_is_told_they_arent_an_admin_not_that_the_crew_vanished(world):
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Thursday Pool Crew", visibility="private",
                        admin_id=world["ana_id"])["id"]
    link = invites.create(ana, crew, by=world["ana_id"])
    invites.redeem(bruno, link["token"], world["bruno_id"])

    with pytest.raises(ValueError, match="only a crew admin"):
        invites.create(bruno, crew, by=world["bruno_id"])
    with pytest.raises(ValueError, match="only a crew admin"):
        invites.revoke(bruno, link["invite_id"], by=world["bruno_id"])


def test_only_an_admin_can_mint_list_or_revoke(world):
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    for call in (lambda: invites.create(world["bruno"], world["crew"], by=world["bruno_id"]),
                 lambda: invites.for_crew(world["bruno"], world["crew"], by=world["bruno_id"]),
                 lambda: invites.revoke(world["bruno"], link["invite_id"], by=world["bruno_id"])):
        with pytest.raises(ValueError):
            call()


def test_a_bad_token_fails_exactly_like_a_stale_one(world):
    """Refusals must not let a link be used to probe what exists."""
    link = invites.create(world["ana"], world["crew"], by=world["ana_id"])
    invites.revoke(world["ana"], link["invite_id"], by=world["ana_id"])

    for token in ("", "not-a-real-token", link["token"]):
        with pytest.raises(ValueError, match="isn't valid"):
            invites.redeem(world["bruno"], token, world["bruno_id"])


def test_ttl_is_clamped_so_a_link_is_never_immortal(world):
    forever = invites.create(world["ana"], world["crew"], by=world["ana_id"], ttl_hours=99999)
    cap = (datetime.datetime.now(datetime.timezone.utc)
           + datetime.timedelta(hours=invites.MAX_TTL_HOURS + 1)).isoformat()
    assert forever["expires_at"] < cap


# ---- gateway ----------------------------------------------------------------

def test_gateway_link_journey_between_two_accounts(cfg):
    client = TestClient(create_app(cfg))
    for handle in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": handle, "password": PW})
    tok = {h: client.post("/v1/auth/login", json={"handle": h, "password": PW}).json()["token"]
           for h in ("ana", "bruno")}
    head = lambda h: {"Authorization": f"Bearer {tok[h]}"}
    ana_id = client.get("/v1/auth/me", headers=head("ana")).json()["account_id"]

    crew = client.post("/v1/crews", json={
        "name": "Thursday Pool Crew", "visibility": "private", "admin_id": ana_id},
        headers=head("ana")).json()["id"]

    link = client.post("/v1/crews/invite-link", json={"crew_id": crew},
                       headers=head("ana")).json()
    assert link["token"]

    joined = client.post("/v1/crews/invite-link/redeem", json={"token": link["token"]},
                         headers=head("bruno")).json()
    assert joined["joined"] is True
    assert client.get(f"/v1/crews/{crew}", headers=head("ana")).json()["member_count"] == 2

    # revoked links stop working, and listing never leaks the secret
    client.post("/v1/crews/invite-link/revoke", json={"invite_id": link["invite_id"]},
                headers=head("ana"))
    listed = client.get("/v1/crews/invite-link", params={"crew_id": crew},
                        headers=head("ana")).json()["invites"]
    assert listed[0]["active"] is False and "token" not in listed[0]
