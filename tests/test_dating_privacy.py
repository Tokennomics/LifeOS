"""G1 — the invariant, proven: a non-match cannot see dating availability.

The ROADMAP names the five routes this has to hold against, and there is one test for each:
**not by listing, not by id, not by the feed, not by asking for `visibility=public`, and not
via a forged grant.** Held to the same standard as the isolation work — three real accounts,
not one graph pretending.

Carla is the adversary throughout. She is a legitimate signed-up adult with a working
account, which is the realistic threat: not an outsider with a database dump, but the third
person in the climbing crew.
"""

import datetime

import pytest

from gateway import accounts
from modules.dating import gate, mutual_match
from modules.discover import discover
from modules.security import crypto_tokens
from substrate import SYSTEM_OWNER
from substrate.graph import Graph

KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"      # 32 chars, test-only
PW = "correct-horse-battery"
CLIMBING = "crew_lisbon_climbing"


def _adult_dob() -> str:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return today.replace(year=today.year - 30).isoformat()


@pytest.fixture
def world(graph, monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    monkeypatch.setenv(gate.ENABLE_VAR, "1")
    made = {"root": graph}
    for name in ("ana", "bruno", "carla"):
        account = accounts.register(graph, name, PW)
        made[name] = Graph(graph.conn, graph.bus, default_owner=account["owner_id"])
        made[f"{name}_id"] = account["account_id"]
        gate.declare_age(graph, account["account_id"], _adult_dob())

    # Ana and Bruno match at climbing. Carla is in the same crew and interested in Ana.
    made["ana_intent"] = mutual_match.express_interest(
        made["ana"], made["bruno_id"], CLIMBING, account_id=made["ana_id"])["intent_id"]
    mutual_match.express_interest(
        made["bruno"], made["ana_id"], CLIMBING, account_id=made["bruno_id"])
    mutual_match.express_interest(
        made["carla"], made["ana_id"], CLIMBING, account_id=made["carla_id"])
    return made


def _carla(world, scopes=("content:read", "people:read")):
    return world["carla"].session("attacker", set(scopes))


# ---- 1. not by listing -------------------------------------------------------

def test_not_by_listing(world):
    """Carla lists every content entity she can reach and finds no one's dating data."""
    session = _carla(world)
    for attrs in ({}, {"type": "dating_intent"}, {"type": "dating_handshake"},
                  {"type": "dating_adult"}):
        for row in session.find_entities("content", attrs or None, limit=500):
            assert row["attrs"].get("type") != "dating_intent" or \
                row["attrs"].get("user_id") == world["carla_id"]


def test_listing_the_published_rows_yields_a_count_and_no_names(world):
    """The handshakes ARE public. That is safe only because they are system-owned digests:
    a full scan is a population count, not a directory of who is looking."""
    rows = _carla(world).find_public("content", {"type": "dating_handshake"}, limit=500)
    assert len(rows) == 3
    for row in rows:
        assert row["owner_id"] == SYSTEM_OWNER
        assert set(row["attrs"]) == {"type", "rk", "visibility", "created_at"}
        blob = repr(row)
        for known in ("ana", "bruno", "carla", world["ana_id"], world["bruno_id"],
                      world["carla_id"], CLIMBING):
            assert known not in blob


# ---- 2. not by id ------------------------------------------------------------

def test_not_by_id(world):
    """Even holding Ana's intent id — which no API hands out — reads as missing."""
    intent_id = world["ana_intent"]
    session = _carla(world)
    assert session.get_entity(intent_id) is None
    assert session.get_public(intent_id) is None
    assert session.get_if_granted(intent_id, world["carla_id"], {"content:read"}) is None


# ---- 3. not by the feed ------------------------------------------------------

def test_not_by_the_feed(world):
    feed = discover.feed(world["carla"], cities=["Lisbon"], limit=50)
    found = discover.find(world["carla"], city="Lisbon")
    blob = repr(feed) + repr(found)
    for leak in ("dating", "dating_intent", "dating_handshake", world["ana_id"]):
        assert leak not in blob


# ---- 4. not by asking for visibility=public ----------------------------------

def test_not_by_asking_for_visibility_public(world):
    """`find_public` forces `visibility=public`, so the private intent is unreachable
    through it no matter what the caller asks for."""
    session = _carla(world)
    assert session.find_public("content", {"type": "dating_intent"}, limit=500) == []
    assert session.find_public(
        "content", {"type": "dating_intent", "visibility": "private"}, limit=500) == []
    assert session.find_public("content", {"type": "dating_adult"}, limit=500) == []


def test_an_author_cannot_publish_their_own_intent_by_accident(world):
    """The intent is created private. Nothing in the module ever republishes it."""
    mine = world["ana"].session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_intent"}, limit=10)
    assert all(r["attrs"].get("visibility") == "private" for r in mine)


# ---- 5. not via a forged grant -----------------------------------------------

def test_not_via_a_forged_grant(world):
    """Grants are not owner-authenticated — any session with content:write can write one.
    That is a known substrate gotcha, and the design answer here is that dating has NO
    shared entity to forge a grant on: matching never consults grants, so writing one
    changes nothing."""
    attacker = world["carla"].session("attacker", {"content:read", "content:write"})
    attacker.grant(world["carla_id"], "content:read", world["ana_intent"], source="attack")

    assert mutual_match.check_matches(world["carla"], world["carla_id"]) == [], \
        "a grant must not be able to manufacture a match"
    assert mutual_match.express_interest(
        world["carla"], world["ana_id"], CLIMBING,
        account_id=world["carla_id"])["is_mutual"] is False


def test_a_forged_grant_on_a_handshake_reveals_nothing(world):
    """The handshake is the only shared row, and it is already public — granting yourself
    a role on it buys exactly the digest you could already see."""
    system = Graph(world["root"].conn, world["root"].bus, default_owner=SYSTEM_OWNER)
    handshake = system.session("t", {"content:read"}).find_entities(
        "content", {"type": "dating_handshake"}, limit=1)[0]
    attacker = world["carla"].session("attacker", {"content:read", "content:write"})
    attacker.grant(world["carla_id"], "content:read", handshake["id"], source="attack")

    got = attacker.get_if_granted(handshake["id"], world["carla_id"], {"content:read"})
    assert set(got["attrs"]) == {"type", "rk", "visibility", "created_at"}
    for known in (world["ana_id"], world["bruno_id"], CLIMBING):
        assert known not in repr(got)


# ---- the digest itself -------------------------------------------------------

def test_carla_cannot_confirm_a_match_she_is_not_part_of(world):
    """Ana and Bruno matched. Carla knows both ids and the activity — the whole plaintext
    — and still cannot compute the digest, because it is keyed."""
    real = mutual_match._rendezvous(world["ana_id"], world["bruno_id"], CLIMBING)
    published = {r["attrs"]["rk"] for r in
                 _carla(world).find_public("content", {"type": "dating_handshake"}, limit=50)}
    assert real in published, "the fixture must actually have matched them"

    import hashlib
    guesses = {
        hashlib.sha256(f"{world['ana_id']}{world['bruno_id']}{CLIMBING}".encode()).hexdigest(),
        hashlib.sha256(f"{world['ana_id']}|{world['bruno_id']}|{CLIMBING}".encode()).hexdigest(),
        hashlib.sha256(CLIMBING.encode()).hexdigest(),
    }
    assert not (guesses & published), "an unkeyed digest would be trivially reconstructible"


def test_the_digest_is_directional(world):
    a, b = world["ana_id"], world["bruno_id"]
    assert mutual_match._rendezvous(a, b, CLIMBING) != mutual_match._rendezvous(b, a, CLIMBING)


def test_a_different_signing_key_yields_a_different_digest(world, monkeypatch):
    """Rotating the key invalidates outstanding declarations rather than silently
    preserving them — matching is bound to the deployment, not to a guessable string."""
    before = mutual_match._rendezvous(world["ana_id"], world["bruno_id"], CLIMBING)
    monkeypatch.setenv(crypto_tokens.ENV_VAR, "Zt4Kw8Lm2QpXv6Nr9Bc3JsHy5Ff7Gd1A")
    assert mutual_match._rendezvous(world["ana_id"], world["bruno_id"], CLIMBING) != before
