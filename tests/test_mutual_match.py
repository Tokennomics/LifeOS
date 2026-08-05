"""The two tests that used to live here passed *because* the module was broken.

The first one built the "other user" like this:

    user2_session = graph.session("dating", {"*"})
    user2_session.create_entity("content", {"type": "dating_intent",
                                            "user_id": "acc-user2", ...})

— on the caller's own graph, so `acc-user2` was never a second account at all, just a row
the caller owned. That is the only condition under which the old owner-scoped lookup could
ever find it, so the test proved the inverse of its name: matching worked exactly when both
parties shared one `owner_id`, which in production is never. Two real accounts both got
`is_mutual: False` forever.

The second asserted `/v1/dating/interest` returns 200 with no account, no age declaration
and no feature flag — which is precisely the ungated state the kill-gates exist to prevent.

Both are kept below, inverted: same setup, opposite expectation. Real cross-account
matching is proven in tests/test_dating_match.py, against accounts that actually exist.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import accounts
from gateway.main import create_app
from modules.dating import gate, mutual_match
from modules.security import crypto_tokens
from substrate.graph import Graph

KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"      # 32 chars, test-only
PW = "correct-horse-battery"


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    monkeypatch.setenv(gate.ENABLE_VAR, "1")


def test_a_fabricated_intent_in_your_own_slice_is_not_a_match(graph: Graph, live):
    """The original trap. Writing a `dating_intent` that claims to be someone else's must
    not produce a match — otherwise anyone can manufacture consent on another person's
    behalf by writing one row in their own graph."""
    account = accounts.register(graph, "ana", PW)
    ana = Graph(graph.conn, graph.bus, default_owner=account["owner_id"])
    me = account["account_id"]
    today = datetime.datetime.now(datetime.timezone.utc).date()
    gate.declare_age(graph, me, today.replace(year=today.year - 30).isoformat())

    first = mutual_match.express_interest(ana, "acc-user2", "sushi-night", account_id=me)
    assert first["outcome"] == "stored_privately"

    ana.session("dating", {"content:read", "content:write"}).create_entity(
        "content", {"type": "dating_intent", "user_id": "acc-user2", "target": me,
                    "activity": "sushi-night", "visibility": "private"},
        source="forgery")

    second = mutual_match.express_interest(ana, "acc-user2", "sushi-night", account_id=me)
    assert second["is_mutual"] is False, "consent cannot be forged by writing a row"
    assert mutual_match.check_matches(ana, me) == []


def test_the_endpoints_are_gated_rather_than_openly_200(cfg):
    """No flag, no key, no age declaration — the surface must refuse, not serve."""
    client = TestClient(create_app(cfg))
    assert client.post("/v1/dating/interest", json={
        "target_account_id": "acc-user2", "activity_id": "climbing-crew"}).status_code == 503
    assert client.get("/v1/dating/matches").status_code == 503
