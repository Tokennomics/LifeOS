"""GDPR Art. 17 — delete my account, and everything of mine.

Export has existed since Law 2; erasure did not, which made "the graph is the user's" only
half true. The interesting cases are all about the boundary: what goes, what survives
because it belongs to someone else too, and what survives *deliberately* because deletion
would otherwise be a feature for the wrong person.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import accounts, rate_limiter
from gateway.main import create_app
from modules.crews import crews
from modules.privacy import erasure
from substrate import SYSTEM_OWNER
from substrate.graph import Graph

PW = "correct-horse-battery"
KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")
    monkeypatch.setenv("LIFEOS_SIGNING_KEY", KEY)


@pytest.fixture
def world(cfg):
    client = TestClient(create_app(cfg))
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
    head, ids, owners = {}, {}, {}
    for name in ("ana", "bruno"):
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        head[name] = {"Authorization": f"Bearer {token}"}
        me = client.get("/v1/auth/me", headers=head[name]).json()
        ids[name], owners[name] = me["account_id"], me["owner_id"]
    client.post("/v1/capture", headers=head["ana"], json={"text": "Ana's therapy notes"})
    client.post("/v1/capture", headers=head["ana"], json={"text": "Ana's salary is 91000"})
    client.post("/v1/capture", headers=head["bruno"], json={"text": "Bruno's own note"})
    return {"c": client, "h": head, "id": ids, "owner": owners,
            "graph": client.app.state.graph}


def _rows(world, sql, params=()):
    return world["graph"].conn.execute(sql, params).fetchall()


# ---- see it before you do it -------------------------------------------------

def test_preview_says_what_would_go(world):
    body = world["c"].get("/v1/auth/account/erase-preview", headers=world["h"]["ana"]).json()
    assert body["entities"] >= 2
    assert "snapshots" in body["retention_note"]


def test_preview_does_not_delete_anything(world):
    world["c"].get("/v1/auth/account/erase-preview", headers=world["h"]["ana"])
    after = world["c"].get("/v1/export", headers=world["h"]["ana"]).json()
    assert "therapy" in repr(after["entities"])


# ---- the guards --------------------------------------------------------------

def test_a_wrong_password_does_not_erase(world):
    r = world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                        json={"password": "not-it", "confirm": "ana"})
    assert r.status_code == 401
    assert "therapy" in repr(world["c"].get("/v1/export", headers=world["h"]["ana"]).json())


def test_the_handle_must_be_typed_to_confirm(world):
    """The oldest guard against a mis-tap, and the only action here with no undo."""
    r = world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                        json={"password": PW, "confirm": ""})
    assert r.status_code == 400 and "ana" in r.json()["detail"]
    r = world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                        json={"password": PW, "confirm": "bruno"})
    assert r.status_code == 400


def test_a_valid_token_alone_is_not_enough(world):
    """A borrowed phone holds a valid session. It must not be able to erase a life."""
    assert world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                           json={"password": "", "confirm": "ana"}).status_code == 401


# ---- the erasure itself ------------------------------------------------------

def test_erasing_removes_every_entity_edge_and_observation(world):
    receipt = world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                              json={"password": PW, "confirm": "ana"}).json()
    assert receipt["erased"] is True and receipt["entities"] >= 2

    owner = world["owner"]["ana"]
    assert _rows(world, "SELECT * FROM entities WHERE owner_id = ?", (owner,)) == []
    leftover = _rows(world, "SELECT * FROM entities WHERE attrs LIKE '%therapy%'")
    assert leftover == [], "the text itself must be gone, not just the index"


def test_the_session_stops_working_immediately(world):
    world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                    json={"password": PW, "confirm": "ana"})
    assert world["c"].get("/v1/auth/me", headers=world["h"]["ana"]).status_code == 401


def test_the_handle_cannot_log_in_afterwards(world):
    world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                    json={"password": PW, "confirm": "ana"})
    assert world["c"].post("/v1/auth/login",
                           json={"handle": "ana", "password": PW}).status_code == 401


def test_nobody_elses_data_is_touched(world):
    world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                    json={"password": PW, "confirm": "ana"})
    bruno = world["c"].get("/v1/export", headers=world["h"]["bruno"]).json()
    assert "Bruno's own note" in repr(bruno["entities"])
    assert world["c"].get("/v1/auth/me", headers=world["h"]["bruno"]).status_code == 200


def test_no_observation_row_survives_pointing_at_a_ghost(world):
    world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                    json={"password": PW, "confirm": "ana"})
    dangling = _rows(world, "SELECT o.id FROM observations o "
                            "LEFT JOIN entities e ON e.id = o.entity_id "
                            "WHERE e.id IS NULL AND o.entity_id IS NOT NULL")
    assert dangling == [], "provenance rows outlived the entities they describe"


def test_the_handle_becomes_available_again(world):
    world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                    json={"password": PW, "confirm": "ana"})
    assert world["c"].post("/v1/auth/register",
                           json={"handle": "ana", "password": PW}).status_code == 200


# ---- shared things survive; you vanish from them -----------------------------

def test_you_disappear_from_a_crew_without_deleting_it(world):
    """A crew is other people's too. Erasure removes you from the roster, not the room."""
    graph = world["graph"]
    bruno = Graph(graph.conn, graph.bus, default_owner=world["owner"]["bruno"])
    crew = crews.create(bruno, "Lisbon Climbers", city="Lisbon", visibility="public",
                        admission="open", admin_id=world["id"]["bruno"])["id"]
    crews.request_join(Graph(graph.conn, graph.bus, default_owner=world["owner"]["ana"]),
                       crew, world["id"]["ana"])
    assert world["id"]["ana"] in crews.members(bruno, crew)

    world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                    json={"password": PW, "confirm": "ana"})

    assert crews.get(bruno, crew)["name"] == "Lisbon Climbers"
    assert world["id"]["ana"] not in crews.members(bruno, crew)


# ---- the deliberate exception ------------------------------------------------

def test_an_abuse_report_survives_with_the_identifier_pseudonymised(world, monkeypatch):
    """The hard case. If erasing an account wiped the record of what that account did,
    deletion becomes a feature for the wrong person. Art. 17(3)(e) keeps data needed for
    legal claims — so the account of what happened stays, and the id in it does not."""
    monkeypatch.setenv("LIFEOS_DATING_ENABLED", "1")
    c, h, ids = world["c"], world["h"], world["id"]
    for name in ("ana", "bruno"):
        today = datetime.datetime.now(datetime.timezone.utc).date()
        c.post("/v1/dating/age", headers=h[name],
               json={"date_of_birth": today.replace(year=today.year - 30).isoformat()})
    c.post("/v1/dating/report", headers=h["bruno"],
           json={"subject_account_id": ids["ana"], "reason": "followed me home"})

    c.post("/v1/auth/account/erase", headers=h["ana"],
           json={"password": PW, "confirm": "ana"})

    system = Graph(world["graph"].conn, world["graph"].bus, default_owner=SYSTEM_OWNER)
    reports = system.session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_report"}, limit=10)
    assert len(reports) == 1, "the report must survive the reported party's erasure"
    attrs = reports[0]["attrs"]
    assert attrs["reason"] == "followed me home"
    assert attrs["subject_id"].startswith(erasure.ERASED_PREFIX)
    assert ids["ana"] not in repr(attrs)


def test_the_pseudonym_is_stable_but_one_way():
    a, b = erasure.pseudonym("acc-1"), erasure.pseudonym("acc-1")
    assert a == b, "two reports about the same erased account must still line up"
    assert erasure.pseudonym("acc-2") != a
    assert "acc-1" not in a


def test_erasure_works_even_with_no_signing_key(monkeypatch, world):
    """A user must be able to leave regardless of how the box is configured."""
    monkeypatch.delenv("LIFEOS_SIGNING_KEY", raising=False)
    assert erasure.pseudonym("acc-1").startswith(erasure.ERASED_PREFIX)
    r = world["c"].post("/v1/auth/account/erase", headers=world["h"]["ana"],
                        json={"password": PW, "confirm": "ana"})
    assert r.status_code == 200 and r.json()["erased"] is True


# ---- the substrate primitives ------------------------------------------------

def test_delete_entity_is_owner_scoped(world):
    """Deleting by id must not reach across the owner boundary any more than reading does."""
    graph = world["graph"]
    ana = Graph(graph.conn, graph.bus, default_owner=world["owner"]["ana"])
    bruno = Graph(graph.conn, graph.bus, default_owner=world["owner"]["bruno"])
    mine = ana.session("t", {"content:read"}).find_entities("content", limit=5)[0]["id"]

    from substrate.graph import GraphError
    with pytest.raises(GraphError):
        bruno.session("t", {"content:read", "content:write"}).delete_entity(mine, source="x")
    assert ana.session("t", {"content:read"}).get_entity(mine) is not None


def test_delete_entity_takes_its_edges_with_it(world):
    graph = world["graph"]
    ana = Graph(graph.conn, graph.bus, default_owner=world["owner"]["ana"])
    s = ana.session("t", {"content:read", "content:write", "people:read", "people:write"})
    a = s.create_entity("content", {"type": "note", "text": "a"}, source="t")
    b = s.create_entity("content", {"type": "note", "text": "b"}, source="t")
    s.create_edge(a, b, "feeds", source="t")

    result = s.delete_entity(a, source="t")
    assert result["edges"] == 1
    assert _rows(world, "SELECT * FROM edges WHERE src = ? OR dst = ?", (a, a)) == []
    assert s.get_entity(b) is not None, "the other end survives"
