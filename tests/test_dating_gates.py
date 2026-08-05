"""G0/G2/G4 — the dating surface fails closed.

The module shipped past all five of its ROADMAP kill-gates with zero tests. These are the
two gates that code can actually satisfy (the surface being off by default, and 18+), plus
proof that "off" means off rather than degraded.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.dating import gate
from modules.security import crypto_tokens
from substrate.graph import Graph

KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"      # 32 chars, test-only
PW = "correct-horse-battery"


def _dob(years_old: int) -> str:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return today.replace(year=today.year - years_old).isoformat()


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)


@pytest.fixture
def enabled(monkeypatch, keyed):
    monkeypatch.setenv(gate.ENABLE_VAR, "1")


@pytest.fixture
def ana(graph):
    account = accounts.register(graph, "ana", PW)
    return {"graph": Graph(graph.conn, graph.bus, default_owner=account["owner_id"]),
            "id": account["account_id"]}


# ---- G0/G4: off unless an operator turns it on ------------------------------

def test_the_surface_is_off_by_default(keyed):
    """Hosting and real users are gates code cannot satisfy, so the default is off."""
    state = gate.availability()
    assert state["available"] is False
    assert any(gate.ENABLE_VAR in r for r in state["reasons"])


def test_off_means_every_entry_point_refuses(graph, ana, monkeypatch):
    from modules.dating import mutual_match
    monkeypatch.delenv(gate.ENABLE_VAR, raising=False)
    for call in (
        lambda: mutual_match.express_interest(ana["graph"], "someone", "climbing"),
        lambda: mutual_match.check_matches(ana["graph"], account_id=ana["id"]),
        lambda: gate.declare_age(graph, ana["id"], _dob(30)),
    ):
        with pytest.raises(gate.DatingUnavailable):
            call()


def test_an_unset_signing_key_also_takes_the_surface_down(monkeypatch):
    """Matching is blinded with the signing key. No key is not a weaker mode; it is off."""
    monkeypatch.setenv(gate.ENABLE_VAR, "1")
    monkeypatch.delenv(crypto_tokens.ENV_VAR, raising=False)
    state = gate.availability()
    assert state["available"] is False
    assert any(crypto_tokens.ENV_VAR in r for r in state["reasons"])


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_only_an_explicit_yes_turns_it_on(monkeypatch, keyed, value):
    monkeypatch.setenv(gate.ENABLE_VAR, value)
    assert gate.surface_enabled() is False


# ---- G2: over 18 -------------------------------------------------------------

def test_an_adult_can_declare_and_is_remembered(graph, ana, enabled):
    result = gate.declare_age(graph, ana["id"], _dob(31))
    assert result["adult"] is True
    assert result["method"] == gate.SELF_DECLARED
    assert gate.is_adult(graph, ana["id"]) is True


def test_a_minor_is_refused(graph, ana, enabled):
    with pytest.raises(gate.AgeGateError):
        gate.declare_age(graph, ana["id"], _dob(17))
    assert gate.is_adult(graph, ana["id"]) is False


def test_a_refused_declaration_stores_nothing_about_the_minor(graph, ana, enabled):
    """Recording the refusal would mean holding data about a child in order to prove we
    hold none."""
    dob = _dob(15)
    with pytest.raises(gate.AgeGateError):
        gate.declare_age(graph, ana["id"], dob)
    everything = graph.session("test", {"content:read"}).find_public("content", limit=500)
    system = Graph(graph.conn, graph.bus, default_owner=None)
    rows = system.session("test", {"content:read"}).find_entities("content", limit=500)
    blob = repr(everything) + repr(rows)
    assert dob not in blob
    assert "dating_adult" not in blob


def test_the_date_of_birth_is_never_persisted(graph, ana, enabled):
    """A DOB is needed to check an age and useless afterwards, so only the derived fact
    is kept."""
    dob = _dob(29)
    gate.declare_age(graph, ana["id"], dob)
    system = Graph(graph.conn, graph.bus, default_owner=None)
    rows = system.session("test", {"content:read"}).find_entities(
        "content", {"type": "dating_adult"}, limit=10)
    assert len(rows) == 1
    assert dob not in repr(rows[0]["attrs"])
    assert set(rows[0]["attrs"]) == {
        "type", "account_id", "adult", "min_age", "method", "declared_at"}


def test_the_day_before_the_eighteenth_birthday_is_still_a_minor(graph, ana, enabled):
    """Whole years, birthday-aware — `days // 365` gets this wrong across leap years."""
    today = datetime.datetime.now(datetime.timezone.utc).date()
    almost = today.replace(year=today.year - 18) + datetime.timedelta(days=1)
    with pytest.raises(gate.AgeGateError):
        gate.declare_age(graph, ana["id"], almost.isoformat())


@pytest.mark.parametrize("bad", ["", "not-a-date", "21/03/1994", "1994-13-45"])
def test_a_malformed_date_is_a_bad_request_not_an_adult(graph, ana, enabled, bad):
    with pytest.raises(ValueError):
        gate.declare_age(graph, ana["id"], bad)
    assert gate.is_adult(graph, ana["id"]) is False


def test_a_future_date_of_birth_is_refused(graph, ana, enabled):
    future = (datetime.datetime.now(datetime.timezone.utc).date()
              + datetime.timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        gate.declare_age(graph, ana["id"], future)


def test_declaring_twice_updates_rather_than_duplicates(graph, ana, enabled):
    gate.declare_age(graph, ana["id"], _dob(31))
    gate.declare_age(graph, ana["id"], _dob(31))
    system = Graph(graph.conn, graph.bus, default_owner=None)
    rows = system.session("test", {"content:read"}).find_entities(
        "content", {"type": "dating_adult"}, limit=10)
    assert len(rows) == 1


def test_declaring_is_per_account_not_global(graph, ana, enabled):
    accounts.register(graph, "bruno", PW)
    gate.declare_age(graph, ana["id"], _dob(31))
    assert gate.is_adult(graph, "some-other-account") is False


# ---- the gateway says which failure it is ------------------------------------

def test_gateway_reports_503_when_the_surface_is_off(cfg, monkeypatch, keyed):
    monkeypatch.delenv(gate.ENABLE_VAR, raising=False)
    client = TestClient(create_app(cfg))
    r = client.post("/v1/dating/interest",
                    json={"target_account_id": "someone", "activity_id": "climbing"})
    assert r.status_code == 503
    assert r.json()["detail"].startswith("dating is unavailable")


def test_gateway_reports_403_when_the_caller_has_not_declared(cfg, enabled):
    """503 and 403 are different facts: the server can serve this, you may not use it."""
    client = TestClient(create_app(cfg))
    r = client.post("/v1/dating/interest",
                    json={"target_account_id": "someone", "activity_id": "climbing"})
    assert r.status_code == 403


def test_availability_endpoint_never_names_a_person(cfg, monkeypatch, keyed):
    monkeypatch.delenv(gate.ENABLE_VAR, raising=False)
    body = TestClient(create_app(cfg)).get("/v1/dating/availability").json()
    assert body["available"] is False
    assert body["reasons"]
