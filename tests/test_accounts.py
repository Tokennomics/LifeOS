"""Accounts — identity, sessions, and the isolation that makes multi-user real."""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app

PW = "correct-horse-battery"


# ---- credentials ------------------------------------------------------------

def test_register_and_login_round_trip(graph):
    acct = accounts.register(graph, "Ana", PW)
    assert acct["handle"] == "ana"                    # handles normalise
    assert acct["owner_id"]                            # each account owns its own slice

    out = accounts.login(graph, "ANA", PW)             # case-insensitive
    assert out["owner_id"] == acct["owner_id"]
    caller = accounts.resolve(graph, out["token"])
    assert caller["handle"] == "ana" and caller["owner_id"] == acct["owner_id"]


def test_secrets_are_never_stored_in_the_clear(graph):
    accounts.register(graph, "ana", PW)
    out = accounts.login(graph, "ana", PW)
    session = accounts._sys(graph)

    stored = session.find_entities("content", {"type": "account"}, limit=1)[0]["attrs"]
    assert PW not in str(stored)                       # no plaintext password anywhere
    assert stored["password_hash"] != PW and len(stored["salt"]) == 32

    sess = session.find_entities("content", {"type": "auth_session"}, limit=1)[0]["attrs"]
    assert out["token"] not in str(sess)               # only the token's hash is kept


def test_bad_credentials_are_indistinguishable(graph):
    accounts.register(graph, "ana", PW)
    with pytest.raises(ValueError) as wrong_pw:
        accounts.login(graph, "ana", "not-the-password")
    with pytest.raises(ValueError) as unknown:
        accounts.login(graph, "nobody", PW)
    assert str(wrong_pw.value) == str(unknown.value)   # no user enumeration


def test_registration_rules(graph):
    accounts.register(graph, "ana", PW)
    with pytest.raises(ValueError):
        accounts.register(graph, "ANA", PW)             # handle taken (case-insensitive)
    with pytest.raises(ValueError):
        accounts.register(graph, "", PW)
    with pytest.raises(ValueError):
        accounts.register(graph, "bob", "short")        # too weak


# ---- sessions are revocable -------------------------------------------------

def test_logout_revokes_one_session(graph):
    accounts.register(graph, "ana", PW)
    a, b = accounts.login(graph, "ana", PW), accounts.login(graph, "ana", PW)
    assert accounts.logout(graph, a["token"])["revoked"] is True
    assert accounts.resolve(graph, a["token"]) is None
    assert accounts.resolve(graph, b["token"]) is not None      # the other still works


def test_logout_everywhere_cuts_all_sessions(graph):
    acct = accounts.register(graph, "ana", PW)
    tokens = [accounts.login(graph, "ana", PW)["token"] for _ in range(3)]
    assert accounts.revoke_all(graph, acct["account_id"])["revoked"] == 3
    assert all(accounts.resolve(graph, t) is None for t in tokens)
    assert accounts.sessions(graph, acct["account_id"]) == []


def test_expired_sessions_stop_working(graph):
    accounts.register(graph, "ana", PW)
    out = accounts.login(graph, "ana", PW, ttl_hours=1)
    assert accounts.resolve(graph, out["token"]) is not None
    # age it out
    accounts._sys(graph).update_entity(
        out["session_id"],
        {"expires_at": (datetime.datetime.now(datetime.timezone.utc)
                        - datetime.timedelta(hours=1)).isoformat()},
        source="test")
    assert accounts.resolve(graph, out["token"]) is None


def test_unknown_tokens_resolve_to_nobody(graph):
    assert accounts.resolve(graph, "made-up") is None
    assert accounts.resolve(graph, "") is None


# ---- isolation --------------------------------------------------------------

def test_two_accounts_cannot_see_each_others_data(cfg):
    client = TestClient(create_app(cfg))
    for handle in ("ana", "bruno"):
        assert client.post("/v1/auth/register",
                           json={"handle": handle, "password": PW}).status_code == 200
    ana = client.post("/v1/auth/login", json={"handle": "ana", "password": PW}).json()["token"]
    bruno = client.post("/v1/auth/login", json={"handle": "bruno", "password": PW}).json()["token"]
    head = lambda t: {"Authorization": f"Bearer {t}"}

    client.post("/v1/vision", json={"text": "Ana's vision\n- Ana's goal"}, headers=head(ana))
    client.post("/v1/vision", json={"text": "Bruno's vision\n- Bruno's goal"}, headers=head(bruno))

    ana_visions = client.get("/v1/vision", headers=head(ana)).json()["visions"]
    bruno_visions = client.get("/v1/vision", headers=head(bruno)).json()["visions"]
    assert [v["title"] for v in ana_visions] == ["Ana's vision"]
    assert [v["title"] for v in bruno_visions] == ["Bruno's vision"]

    # knowing an id is not enough: to Bruno, Ana's goal simply does not exist
    ana_goal = client.get("/v1/goals", headers=head(ana)).json()["goals"][0]["id"]
    assert client.post("/v1/focus", json={"goal_id": ana_goal, "focus": True},
                       headers=head(bruno)).status_code == 404
    assert client.post("/v1/focus", json={"goal_id": ana_goal, "focus": True},
                       headers=head(ana)).status_code == 200

    # and the export is per-account, not the whole database
    assert len(client.get("/v1/export", headers=head(ana)).json()["entities"]) == 2


def test_login_required_once_accounts_exist(cfg):
    client = TestClient(create_app(cfg))
    assert client.get("/v1/vision").status_code == 200          # legacy mode, wide open
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    assert client.get("/v1/vision").status_code == 401          # now it's an account system
    assert client.get("/v1/vision", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_owner_key_still_works_after_accounts_exist(cfg):
    cfg["gateway"]["auth_token"] = "owner-key"
    client = TestClient(create_app(cfg))
    owner = {"Authorization": "Bearer owner-key"}
    client.post("/v1/vision", json={"text": "Owner vision\n- goal"}, headers=owner)
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})

    me = client.get("/v1/auth/me", headers=owner).json()
    assert me["mode"] == "owner-key"                             # the bot/scripts keep working
    assert [v["title"] for v in client.get("/v1/vision", headers=owner).json()["visions"]] \
        == ["Owner vision"]


def test_me_and_logout_through_the_api(cfg):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login", json={"handle": "ana", "password": PW}).json()["token"]
    head = {"Authorization": f"Bearer {token}"}

    me = client.get("/v1/auth/me", headers=head).json()
    assert me["handle"] == "ana" and me["mode"] == "account" and len(me["sessions"]) == 1

    assert client.post("/v1/auth/logout", headers=head).json()["revoked"] is True
    assert client.get("/v1/auth/me", headers=head).status_code == 401


def test_login_failure_is_401_and_registration_conflict_is_400(cfg):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    assert client.post("/v1/auth/login", json={"handle": "ana", "password": "wrong"}).status_code == 401
    assert client.post("/v1/auth/register", json={"handle": "ana", "password": PW}).status_code == 400
