"""G3 — report and block that work outside a crew, and outlive it.

`crews.report` takes a `crew_id` and files against it. A date is one person alone with
someone they met online, and the thing worth reporting usually happens after everyone has
left the crew — sometimes after the crew is gone. These tests hold that line: no crew is
ever created here, and the safety calls still work.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.dating import gate, safety
from modules.security import crypto_tokens
from substrate import SYSTEM_OWNER
from substrate.graph import Graph

KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"      # 32 chars, test-only
PW = "correct-horse-battery"


def _adult_dob() -> str:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return today.replace(year=today.year - 30).isoformat()


@pytest.fixture
def world(graph, monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    monkeypatch.setenv(gate.ENABLE_VAR, "1")
    made = {"root": graph}
    for name in ("ana", "bruno"):
        account = accounts.register(graph, name, PW)
        made[name] = Graph(graph.conn, graph.bus, default_owner=account["owner_id"])
        made[f"{name}_id"] = account["account_id"]
        gate.declare_age(graph, account["account_id"], _adult_dob())
    return made


# ---- blocking ----------------------------------------------------------------

def test_a_block_needs_no_crew_and_no_admin(world):
    result = safety.block(world["ana"], world["bruno_id"], account_id=world["ana_id"])
    assert result["blocked"] is True
    assert safety.is_blocked(world["root"], world["ana_id"], world["bruno_id"]) is True


def test_a_block_is_mutual_invisibility_not_a_one_way_mute(world):
    """Sorting the pair before hashing makes one row cover both directions, which is also
    the right semantics: the blocked party must not be able to reach back."""
    safety.block(world["ana"], world["bruno_id"], account_id=world["ana_id"])
    assert safety.is_blocked(world["root"], world["bruno_id"], world["ana_id"]) is True


def test_either_side_can_block(world):
    safety.block(world["bruno"], world["ana_id"], account_id=world["bruno_id"])
    assert safety.is_blocked(world["root"], world["ana_id"], world["bruno_id"]) is True


def test_unblocking_works_and_is_idempotent(world):
    safety.block(world["ana"], world["bruno_id"], account_id=world["ana_id"])
    assert safety.unblock(world["ana"], world["bruno_id"],
                          account_id=world["ana_id"])["changed"] is True
    assert safety.is_blocked(world["root"], world["ana_id"], world["bruno_id"]) is False
    assert safety.unblock(world["ana"], world["bruno_id"],
                          account_id=world["ana_id"])["changed"] is False


def test_blocking_twice_does_not_duplicate_the_row(world):
    safety.block(world["ana"], world["bruno_id"], account_id=world["ana_id"])
    safety.block(world["ana"], world["bruno_id"], account_id=world["ana_id"])
    system = Graph(world["root"].conn, world["root"].bus, default_owner=SYSTEM_OWNER)
    rows = system.session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_block"}, limit=50)
    assert len(rows) == 1


def test_the_block_row_is_not_a_readable_list_of_who_avoids_whom(world):
    """Enforcement only ever asks 'are these two blocked', which a digest answers exactly
    as well as two names."""
    safety.block(world["ana"], world["bruno_id"], account_id=world["ana_id"])
    system = Graph(world["root"].conn, world["root"].bus, default_owner=SYSTEM_OWNER)
    row = system.session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_block"}, limit=1)[0]
    assert set(row["attrs"]) == {"type", "pair_key", "active", "created_at"}
    assert world["ana_id"] not in repr(row) and world["bruno_id"] not in repr(row)


def test_you_cannot_block_yourself(world):
    with pytest.raises(ValueError):
        safety.block(world["ana"], world["ana_id"], account_id=world["ana_id"])


# ---- reporting ---------------------------------------------------------------

def test_a_report_needs_no_crew(world):
    result = safety.report(world["ana"], world["bruno_id"], "followed me to the metro",
                           account_id=world["ana_id"], context="after the climbing night")
    assert result["status"] == safety.OPEN
    queue = safety.open_reports(world["root"])
    assert len(queue) == 1
    assert queue[0]["subject_id"] == world["bruno_id"]
    assert queue[0]["context"] == "after the climbing night"


def test_reporting_blocks_immediately(world):
    """The reporter is protected the moment they ask, not whenever the queue is next
    serviced. The safety property has to hold on a day nobody services it."""
    safety.report(world["ana"], world["bruno_id"], "made me uncomfortable",
                  account_id=world["ana_id"])
    assert safety.is_blocked(world["root"], world["ana_id"], world["bruno_id"]) is True


def test_the_moderation_queue_is_readable_by_a_human(world):
    """Deliberately not blinded: a queue nobody can read is not a moderation queue."""
    safety.report(world["ana"], world["bruno_id"], "verbal abuse",
                  account_id=world["ana_id"])
    assert safety.open_reports(world["root"])[0]["reason"] == "verbal abuse"


def test_resolving_closes_the_item_but_keeps_the_block(world):
    """Clearing the queue is not a decision to put those two back in front of each other."""
    report_id = safety.report(world["ana"], world["bruno_id"], "abuse",
                              account_id=world["ana_id"])["report_id"]
    safety.resolve_report(world["root"], report_id, "warned")
    assert safety.open_reports(world["root"]) == []
    assert safety.is_blocked(world["root"], world["ana_id"], world["bruno_id"]) is True


def test_a_report_outlives_the_context_it_came_from(world):
    """No crew was ever created in this module's tests, and the report is still here."""
    safety.report(world["ana"], world["bruno_id"], "assault", account_id=world["ana_id"])
    system = Graph(world["root"].conn, world["root"].bus, default_owner=SYSTEM_OWNER)
    rows = system.session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_report"}, limit=10)
    assert len(rows) == 1
    assert "crew_id" not in rows[0]["attrs"]


def test_reports_are_system_owned_so_neither_party_can_edit_them(world):
    report_id = safety.report(world["ana"], world["bruno_id"], "abuse",
                              account_id=world["ana_id"])["report_id"]
    for who in ("ana", "bruno"):
        session = world[who].session("t", {"content:read", "content:write"})
        assert session.get_entity(report_id) is None
        with pytest.raises(Exception):
            session.update_entity(report_id, {"status": "dismissed"}, source="attack")
    assert safety.open_reports(world["root"])[0]["id"] == report_id


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_report_needs_a_reason(world, reason):
    with pytest.raises(ValueError):
        safety.report(world["ana"], world["bruno_id"], reason, account_id=world["ana_id"])


def test_you_cannot_report_yourself(world):
    with pytest.raises(ValueError):
        safety.report(world["ana"], world["ana_id"], "test", account_id=world["ana_id"])


def test_resolving_an_unknown_report_is_an_error_not_a_silent_pass(world):
    with pytest.raises(ValueError):
        safety.resolve_report(world["root"], "not-a-report")


# ---- the gateway -------------------------------------------------------------

def test_safety_endpoints_are_reachable(cfg, monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    monkeypatch.setenv(gate.ENABLE_VAR, "1")
    client = TestClient(create_app(cfg))

    assert client.post("/v1/dating/report", json={
        "subject_account_id": "someone-else", "reason": "followed me home"}
    ).status_code == 200
    assert client.get("/v1/dating/reports").json()["reports"][0]["reason"] == \
        "followed me home"


def test_reporting_does_not_require_the_dating_surface_to_be_up(cfg, monkeypatch):
    """Turning the feature off must not strand a report about something that already
    happened."""
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    monkeypatch.delenv(gate.ENABLE_VAR, raising=False)
    client = TestClient(create_app(cfg))
    assert client.post("/v1/dating/report", json={
        "subject_account_id": "someone-else", "reason": "assault"}).status_code == 200
