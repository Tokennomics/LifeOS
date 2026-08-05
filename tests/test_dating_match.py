"""Matching across two real accounts — the thing that never worked.

`express_interest` looked the other party's `dating_intent` up with `find_entities`, which
is owner-scoped, so it returned nothing every time and `is_mutual` was permanently False.
Two accounts, both interested, no match. These tests are written against real registered
accounts rather than one graph pretending to be two, because a single-owner test passes
under the old code as well as the new one and would have proved nothing.
"""

import datetime

import pytest

from gateway import accounts
from modules.dating import gate, mutual_match, safety
from modules.security import crypto_tokens
from substrate import SYSTEM_OWNER
from substrate.graph import Graph

KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"      # 32 chars, test-only
PW = "correct-horse-battery"
CLIMBING = "crew_lisbon_climbing"
SUSHI = "crew_lisbon_sushi"


def _adult_dob() -> str:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return today.replace(year=today.year - 30).isoformat()


@pytest.fixture
def world(graph, monkeypatch):
    """Ana, Bruno and Carla as three separate accounts on a live dating surface."""
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    monkeypatch.setenv(gate.ENABLE_VAR, "1")
    made = {}
    for name in ("ana", "bruno", "carla"):
        account = accounts.register(graph, name, PW)
        made[name] = Graph(graph.conn, graph.bus, default_owner=account["owner_id"])
        made[f"{name}_id"] = account["account_id"]
        gate.declare_age(graph, account["account_id"], _adult_dob())
    made["root"] = graph
    return made


def _interest(w, who, target, activity=CLIMBING):
    return mutual_match.express_interest(
        w[who], w[f"{target}_id"], activity, account_id=w[f"{who}_id"])


# ---- the bug ----------------------------------------------------------------

def test_one_sided_interest_is_not_a_match(world):
    result = _interest(world, "ana", "bruno")
    assert result["is_mutual"] is False
    assert result["outcome"] == "stored_privately"
    assert mutual_match.check_matches(world["ana"], world["ana_id"]) == []


def test_reciprocated_interest_matches_across_accounts(world):
    """The whole point. Under the old code both sides got is_mutual: False forever."""
    assert _interest(world, "ana", "bruno")["is_mutual"] is False
    second = _interest(world, "bruno", "ana")
    assert second["is_mutual"] is True
    assert second["outcome"] == "mutual_match"


def test_both_sides_see_the_match_not_just_the_one_who_went_second(world):
    _interest(world, "ana", "bruno")
    _interest(world, "bruno", "ana")

    for who, other in (("ana", "bruno"), ("bruno", "ana")):
        matches = mutual_match.check_matches(world[who], world[f"{who}_id"])
        assert [m["target_account_id"] for m in matches] == [world[f"{other}_id"]]
        assert matches[0]["activity_id"] == CLIMBING


def test_interest_is_scoped_to_the_activity(world):
    """Meeting through a shared activity is the product. Liking someone at climbing is not
    a standing declaration about every room they walk into."""
    _interest(world, "ana", "bruno", CLIMBING)
    _interest(world, "bruno", "ana", SUSHI)
    assert mutual_match.check_matches(world["ana"], world["ana_id"]) == []
    assert mutual_match.check_matches(world["bruno"], world["bruno_id"]) == []


def test_a_third_party_is_not_dragged_into_someone_elses_match(world):
    _interest(world, "ana", "bruno")
    _interest(world, "bruno", "ana")
    assert mutual_match.check_matches(world["carla"], world["carla_id"]) == []


def test_direction_matters(world):
    """A→B and B→A are different declarations; matching on a symmetric key would make
    one person's interest look like two."""
    _interest(world, "ana", "bruno")
    _interest(world, "ana", "carla")
    assert mutual_match.check_matches(world["ana"], world["ana_id"]) == []


def test_expressing_twice_is_idempotent(world):
    first = _interest(world, "ana", "bruno")
    again = _interest(world, "ana", "bruno")
    assert again["intent_id"] == first["intent_id"]
    _interest(world, "bruno", "ana")
    assert len(mutual_match.check_matches(world["ana"], world["ana_id"])) == 1


def test_you_cannot_express_interest_in_yourself(world):
    with pytest.raises(ValueError):
        _interest(world, "ana", "ana")


@pytest.mark.parametrize("target,activity", [("", CLIMBING), ("someone", ""), ("  ", " ")])
def test_blank_arguments_are_refused(world, target, activity):
    with pytest.raises(ValueError):
        mutual_match.express_interest(world["ana"], target, activity,
                                      account_id=world["ana_id"])


# ---- withdrawal is unilateral ------------------------------------------------

def test_either_side_can_end_a_match_alone(world):
    _interest(world, "ana", "bruno")
    _interest(world, "bruno", "ana")
    assert mutual_match.check_matches(world["bruno"], world["bruno_id"])

    mutual_match.withdraw_interest(world["ana"], world["bruno_id"], CLIMBING,
                                   account_id=world["ana_id"])

    assert mutual_match.check_matches(world["ana"], world["ana_id"]) == []
    assert mutual_match.check_matches(world["bruno"], world["bruno_id"]) == [], \
        "withdrawal must take effect for the other party too, without their agreement"


def test_withdrawing_then_re_expressing_works(world):
    _interest(world, "ana", "bruno")
    mutual_match.withdraw_interest(world["ana"], world["bruno_id"], CLIMBING,
                                   account_id=world["ana_id"])
    _interest(world, "bruno", "ana")
    assert mutual_match.check_matches(world["bruno"], world["bruno_id"]) == []

    assert _interest(world, "ana", "bruno")["is_mutual"] is True


def test_withdrawing_something_that_was_never_expressed_is_harmless(world):
    assert mutual_match.withdraw_interest(
        world["ana"], world["carla_id"], SUSHI, account_id=world["ana_id"])["withdrawn"]


# ---- blocks beat matches -----------------------------------------------------

def test_a_block_prevents_a_match_from_forming(world):
    safety.block(world["ana"], world["bruno_id"], account_id=world["ana_id"])
    _interest(world, "bruno", "ana")
    result = _interest(world, "ana", "bruno")
    assert result["is_mutual"] is False
    assert mutual_match.check_matches(world["bruno"], world["bruno_id"]) == []


def test_the_blocked_party_is_not_told_they_were_blocked(world):
    """"Blocked" is the one fact a block exists to withhold. It must look like an ordinary
    unreciprocated interest."""
    safety.block(world["ana"], world["bruno_id"], account_id=world["ana_id"])
    blocked = _interest(world, "bruno", "ana")
    ordinary = _interest(world, "bruno", "carla")
    assert blocked["outcome"] == ordinary["outcome"] == "stored_privately"
    assert blocked["is_mutual"] is ordinary["is_mutual"] is False


def test_a_block_ends_an_existing_match(world):
    _interest(world, "ana", "bruno")
    _interest(world, "bruno", "ana")
    safety.block(world["bruno"], world["ana_id"], account_id=world["bruno_id"])
    assert mutual_match.check_matches(world["ana"], world["ana_id"]) == []
    assert mutual_match.check_matches(world["bruno"], world["bruno_id"]) == []


# ---- what actually gets written ----------------------------------------------

def test_the_published_row_contains_a_digest_and_nothing_else(world):
    _interest(world, "ana", "bruno")
    system = Graph(world["root"].conn, world["root"].bus, default_owner=SYSTEM_OWNER)
    rows = system.session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_handshake"}, limit=10)
    assert len(rows) == 1
    attrs = rows[0]["attrs"]
    assert set(attrs) == {"type", "rk", "visibility", "created_at"}
    assert len(attrs["rk"]) == 64
    assert rows[0]["owner_id"] == SYSTEM_OWNER, \
        "owned by the author, a full scan would be a list of everyone who is looking"


def test_both_sides_agree_on_when_the_match_formed(world):
    """Found by simulation, not by the suite: the first version handed each side the
    OTHER's declaration date, so Ana and Bruno got two different answers to one shared
    question and neither was the date anything happened."""
    _interest(world, "ana", "bruno")
    _interest(world, "bruno", "ana")
    ana = mutual_match.check_matches(world["ana"], world["ana_id"])[0]
    bruno = mutual_match.check_matches(world["bruno"], world["bruno_id"])[0]
    assert ana["matched_at"] == bruno["matched_at"] != ""


def test_the_public_row_carries_a_date_not_a_timestamp(world):
    """Also from simulation. `find_public` orders by created_at, so a microsecond field on
    the one publicly readable row is a global 'somebody declared interest at 21:03:44.118'
    log — which correlates against other public signals to undo the blinding."""
    _interest(world, "ana", "bruno")
    system = Graph(world["root"].conn, world["root"].bus, default_owner=SYSTEM_OWNER)
    row = system.session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_handshake"}, limit=1)[0]
    stamp = row["attrs"]["created_at"]
    assert len(stamp) == 10 and stamp.count("-") == 2, stamp
    datetime.date.fromisoformat(stamp)


def test_the_private_intent_stays_in_its_authors_own_slice(world):
    _interest(world, "ana", "bruno")
    mine = world["ana"].session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_intent"}, limit=10)
    theirs = world["bruno"].session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_intent"}, limit=10)
    assert len(mine) == 1 and theirs == []
