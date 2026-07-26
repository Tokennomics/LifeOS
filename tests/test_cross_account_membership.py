"""Cross-account membership: joining someone else's crew as an ACCOUNT.

`person` stays your own private record of someone you know. An ACCOUNT is who you are
across the system, and that is what shared crews are built from — so a crew can span
accounts without either side needing an entity in the other's graph.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.crews import crews
from substrate.graph import Graph

PW = "correct-horse-battery"


@pytest.fixture
def world(graph):
    """Ana (a Lisbon local) and Bruno (a traveller), as two real accounts."""
    ana = accounts.register(graph, "ana", PW)
    bruno = accounts.register(graph, "bruno", PW)
    return {
        "ana": Graph(graph.conn, graph.bus, default_owner=ana["owner_id"]),
        "bruno": Graph(graph.conn, graph.bus, default_owner=bruno["owner_id"]),
        "ana_id": ana["account_id"], "bruno_id": bruno["account_id"],
    }


# ---- the join that used to be impossible ------------------------------------

def test_traveller_joins_a_drop_in_crew_across_accounts(world):
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Lisbon Sushi Club", topic="sushi", city="Lisbon",
                        visibility="public", admission="open", admin_id=world["ana_id"])["id"]

    found = crews.directory(bruno, city="Lisbon")[0]
    result = crews.request_join(bruno, found["id"], world["bruno_id"])
    assert result["joined"] is True

    # Ana sees him as a member, by handle
    seen = crews.get(ana, crew)
    assert seen["member_count"] == 2
    assert {m["name"] for m in seen["members"]} == {"ana", "bruno"}


def test_approval_crew_queues_the_traveller_for_its_admin(world):
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Curated Climbers", city="Lisbon", visibility="public",
                        admission="approval", admin_id=world["ana_id"])["id"]

    assert crews.request_join(bruno, crew, world["bruno_id"])["requested"] is True
    assert [p["name"] for p in crews.get(ana, crew)["requested"]] == ["bruno"]
    assert world["bruno_id"] not in crews.members(ana, crew)

    crews.approve_request(ana, crew, world["bruno_id"], by=world["ana_id"])
    assert world["bruno_id"] in crews.members(ana, crew)
    assert "bruno" in {m["name"] for m in crews.get(bruno, crew)["members"]}


def test_a_traveller_can_always_leave(world):
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Lisbon Sushi Club", city="Lisbon", visibility="public",
                        admission="open", admin_id=world["ana_id"])["id"]
    crews.request_join(bruno, crew, world["bruno_id"])
    crews.leave(bruno, crew, world["bruno_id"])
    assert world["bruno_id"] not in crews.members(ana, crew)


# ---- what a stranger still cannot do ----------------------------------------

def test_a_stranger_cannot_admin_someone_elses_crew(world):
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Curated Climbers", city="Lisbon", visibility="public",
                        admission="approval", admin_id=world["ana_id"])["id"]
    crews.request_join(bruno, crew, world["bruno_id"])

    with pytest.raises(ValueError):                      # can't wave himself through
        crews.approve_request(bruno, crew, world["bruno_id"], by=world["bruno_id"])
    with pytest.raises(ValueError):                      # can't invite
        crews.invite(bruno, crew, world["bruno_id"], by=world["bruno_id"])
    with pytest.raises(ValueError):                      # can't block the owner
        crews.block(bruno, crew, world["ana_id"], by=world["bruno_id"])
    with pytest.raises(ValueError):                      # can't rewrite the policy
        crews.set_policy(bruno, crew, admission="open", by=world["bruno_id"])
    assert world["bruno_id"] not in crews.members(ana, crew)


def test_an_adminless_public_crew_is_not_adminable_by_a_passer_by(world):
    """Own crews with no admin stay open to their members; that leniency must not leak
    to strangers, or any adminless public crew would be a free-for-all."""
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "No Admin Crew", city="Lisbon", visibility="public",
                        admission="approval")["id"]          # deliberately no admin
    crews.request_join(bruno, crew, world["bruno_id"])
    with pytest.raises(ValueError):
        crews.approve_request(bruno, crew, world["bruno_id"], by=world["bruno_id"])


def test_private_crews_stay_unreachable(world):
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Pool Crew", city="Lisbon", visibility="private",
                        admin_id=world["ana_id"])["id"]
    with pytest.raises(ValueError):
        crews.request_join(bruno, crew, world["bruno_id"])   # not even visible
    with pytest.raises(ValueError):
        crews.get(bruno, crew)


def test_blocking_bars_a_cross_account_traveller(world):
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Lisbon Sushi Club", city="Lisbon", visibility="public",
                        admission="open", admin_id=world["ana_id"])["id"]
    crews.request_join(bruno, crew, world["bruno_id"])
    crews.block(ana, crew, world["bruno_id"], by=world["ana_id"])

    assert world["bruno_id"] not in crews.members(ana, crew)
    with pytest.raises(ValueError):
        crews.request_join(bruno, crew, world["bruno_id"])   # and he can't come back


# ---- local crews are untouched ----------------------------------------------

def test_local_person_membership_still_works(world):
    """The old model — a crew of people in your own graph — keeps working unchanged."""
    ana = world["ana"]
    friend = ana.session("seed", {"people:write"}).create_entity(
        "person", {"name": "Ana's friend"}, source="seed")
    crew = crews.create(ana, "Mates", member_ids=[friend])["id"]
    assert [m["name"] for m in crews.get(ana, crew)["members"]] == ["Ana's friend"]


# ---- gateway ----------------------------------------------------------------

def test_gateway_join_uses_the_callers_own_account(cfg):
    client = TestClient(create_app(cfg))
    for handle in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": handle, "password": PW})
    tok = {h: client.post("/v1/auth/login", json={"handle": h, "password": PW}).json()["token"]
           for h in ("ana", "bruno")}
    head = lambda h: {"Authorization": f"Bearer {tok[h]}"}
    ana_id = client.get("/v1/auth/me", headers=head("ana")).json()["account_id"]

    crew = client.post("/v1/crews", json={
        "name": "Lisbon Sushi Club", "city": "Lisbon", "visibility": "public",
        "admission": "open", "admin_id": ana_id}, headers=head("ana")).json()

    # Bruno finds it in the directory and joins as himself — no person_id needed
    found = client.get("/v1/crews/directory", params={"city": "Lisbon"},
                       headers=head("bruno")).json()["crews"][0]
    joined = client.post("/v1/crews/request", json={"crew_id": found["id"]},
                         headers=head("bruno")).json()
    assert joined["joined"] is True

    ana_view = client.get(f"/v1/crews/{crew['id']}", headers=head("ana")).json()
    assert {m["name"] for m in ana_view["members"]} == {"ana", "bruno"}

    # and he can walk back out
    client.post("/v1/crews/leave", json={"crew_id": found["id"]}, headers=head("bruno"))
    assert client.get(f"/v1/crews/{crew['id']}", headers=head("ana")).json()["member_count"] == 1


def test_my_crews_includes_crews_joined_in_another_account(world):
    """Membership lives in the ACL, not your graph — a crew you joined elsewhere must
    still show up as yours."""
    ana, bruno = world["ana"], world["bruno"]
    crew = crews.create(ana, "Lisbon Sushi Club", city="Lisbon", visibility="public",
                        admission="open", admin_id=world["ana_id"])["id"]
    crews.create(ana, "Ana's Private Thing", visibility="private", admin_id=world["ana_id"])
    crews.request_join(bruno, crew, world["bruno_id"])

    mine = crews.my_crews(bruno, world["bruno_id"])
    assert [c["name"] for c in mine] == ["Lisbon Sushi Club"]
    assert crews.my_crews(ana, world["ana_id"])            # Ana still sees her own
