"""The one deliberate crossing of the owner boundary: published items, read-only.

Two real accounts here, not two owners in one graph — these tests are the guarantee that
a directory can span users without a private thing ever escaping its owner.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.crews import crews
from modules.discover import discover
from substrate.graph import Graph

PW = "correct-horse-battery"


def _soon(days=2):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=days)).isoformat()


def _as(graph, owner_id):
    """A graph scoped to one account, exactly as the gateway builds it per request."""
    return Graph(graph.conn, graph.bus, default_owner=owner_id)


@pytest.fixture
def two_users(graph):
    ana = accounts.register(graph, "ana", PW)
    bruno = accounts.register(graph, "bruno", PW)
    return _as(graph, ana["owner_id"]), _as(graph, bruno["owner_id"])


# ---- the substrate primitive ------------------------------------------------

def test_find_public_crosses_owners_but_only_for_published_items(two_users):
    ana_g, bruno_g = two_users
    crews.create(ana_g, "Lisbon Climbing", topic="climbing", city="Lisbon", visibility="public")
    crews.create(ana_g, "Ana's Secret Supper", topic="food", city="Lisbon", visibility="private")

    session = bruno_g.session("crews", crews.SCOPES)
    found = session.find_public("content", {"type": "crew"})
    assert [c["attrs"]["name"] for c in found] == ["Lisbon Climbing"]

    # Bruno's own owner-scoped read still sees nothing of Ana's at all
    assert session.find_entities("content", {"type": "crew"}) == []


def test_a_caller_cannot_widen_the_public_filter(two_users):
    ana_g, bruno_g = two_users
    crews.create(ana_g, "Ana's Secret Supper", topic="food", visibility="private")
    session = bruno_g.session("crews", crews.SCOPES)
    # asking for private explicitly is overridden — visibility=public is forced
    assert session.find_public("content", {"type": "crew", "visibility": "private"}) == []


def test_get_public_reads_published_only(two_users):
    ana_g, bruno_g = two_users
    public = crews.create(ana_g, "Lisbon Climbing", city="Lisbon", visibility="public")["id"]
    private = crews.create(ana_g, "Secret", visibility="private")["id"]
    session = bruno_g.session("crews", crews.SCOPES)

    assert session.get_public(public)["attrs"]["name"] == "Lisbon Climbing"
    assert session.get_public(private) is None            # knowing the id is not enough
    assert session.get_entity(private) is None            # nor is the owner-scoped path


def test_private_data_of_other_kinds_never_crosses(two_users):
    ana_g, bruno_g = two_users
    ana_g.session("horizon", {"goals:write"}).create_entity(
        "goal", {"level": "vision", "title": "Ana's private vision"}, source="seed")
    session = bruno_g.session("horizon", {"goals:read"})
    assert session.find_public("goal", {"level": "vision"}) == []   # nothing is published


# ---- the directory ----------------------------------------------------------

def test_directory_spans_accounts(two_users):
    ana_g, bruno_g = two_users
    crews.create(ana_g, "Lisbon Climbing", topic="climbing", city="Lisbon",
                 visibility="public", admission="open")
    crews.create(ana_g, "Ana's Pool Crew", topic="pool", city="Lisbon", visibility="private")
    crews.create(bruno_g, "Bruno's Berlin Bouldering", topic="climbing", city="Berlin",
                 visibility="public")

    # Bruno lands in Lisbon and looks for climbing
    found = crews.directory(bruno_g, topic="climbing", city="Lisbon")
    assert [c["name"] for c in found] == ["Lisbon Climbing"]
    assert found[0]["admission"] == "open"

    # everything published, both accounts
    assert sorted(c["name"] for c in crews.directory(bruno_g)) == [
        "Bruno's Berlin Bouldering", "Lisbon Climbing"]
    # Ana's private crew is in none of it
    assert all("Pool" not in c["name"] for c in crews.directory(bruno_g))


def test_directory_shows_size_but_not_another_accounts_roster(two_users):
    ana_g, bruno_g = two_users
    ana_person = ana_g.session("seed", {"people:write"}).create_entity(
        "person", {"name": "Ana's friend"}, source="seed")
    crew = crews.create(ana_g, "Lisbon Climbing", city="Lisbon", visibility="public",
                        member_ids=[ana_person])

    mine = crews.get(ana_g, crew["id"])
    theirs = [c for c in crews.directory(bruno_g) if c["id"] == crew["id"]][0]
    assert [m["name"] for m in mine["members"]] == ["Ana's friend"]   # Ana sees her people
    assert theirs["member_count"] == 1                                # Bruno sees the size
    assert theirs["members"] == []                                    # but not who they are


# ---- discovery + feed across accounts ---------------------------------------

def test_discovery_and_feed_span_accounts_without_leaking(two_users):
    ana_g, bruno_g = two_users
    discover.publish_event(ana_g, "Sushi night at Bairro", start=_soon(), city="Lisbon",
                           topic="sushi", visibility="public")
    discover.publish_event(ana_g, "Ana's pool evening", start=_soon(), city="Lisbon",
                           topic="pool", visibility="private")

    found = discover.find(bruno_g, city="Lisbon", interests=["sushi"])
    assert [e["title"] for e in found["events"]] == ["Sushi night at Bairro"]

    feed = discover.feed(bruno_g, cities=["Lisbon"], interests=["sushi", "pool"])
    titles = [i["title"] for i in feed["items"]]
    assert "Sushi night at Bairro" in titles
    assert "Ana's pool evening" not in titles      # private stays Ana's, at any score


def test_the_lisbon_scenario_across_two_real_accounts(two_users):
    ana_g, bruno_g = two_users
    # Ana runs a public sushi club and a private pool night
    crews.create(ana_g, "Lisbon Sushi Club", topic="sushi", city="Lisbon",
                 visibility="public", admission="open")
    crews.create(ana_g, "Pool Crew", topic="pool", city="Lisbon", visibility="private")
    discover.publish_event(ana_g, "Sushi night at Bairro", start=_soon(), city="Lisbon",
                           topic="sushi", visibility="public")

    # Bruno declares his intent and gets Ana's public things — and nothing else
    intent = discover.set_intent(bruno_g, "Lisbon", ["sushi"])
    result = discover.find_for_intent(bruno_g, intent["intent_id"])
    assert [e["title"] for e in result["events"]] == ["Sushi night at Bairro"]
    assert [c["title"] for c in result["crews"]] == ["Lisbon Sushi Club"]


# ---- gateway ----------------------------------------------------------------

def test_gateway_directory_across_two_logged_in_accounts(cfg):
    client = TestClient(create_app(cfg))
    for handle in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": handle, "password": PW})
    tok = {h: client.post("/v1/auth/login", json={"handle": h, "password": PW}).json()["token"]
           for h in ("ana", "bruno")}
    head = lambda h: {"Authorization": f"Bearer {tok[h]}"}

    client.post("/v1/crews", json={"name": "Lisbon Climbing", "topic": "climbing",
                                   "city": "Lisbon", "visibility": "public"}, headers=head("ana"))
    client.post("/v1/crews", json={"name": "Ana's Pool Crew", "city": "Lisbon",
                                   "visibility": "private"}, headers=head("ana"))

    # Bruno's own crew list is empty; the directory shows Ana's published crew
    assert client.get("/v1/crews", headers=head("bruno")).json()["crews"] == []
    directory = client.get("/v1/crews/directory", params={"city": "Lisbon"},
                           headers=head("bruno")).json()["crews"]
    assert [c["name"] for c in directory] == ["Lisbon Climbing"]

    # and Ana's private crew is unreachable even by id
    ana_crews = client.get("/v1/crews", headers=head("ana")).json()["crews"]
    private_id = [c["id"] for c in ana_crews if c["name"] == "Ana's Pool Crew"][0]
    assert client.get(f"/v1/crews/{private_id}", headers=head("bruno")).status_code == 400
