"""The treasury that showed a community €12,450 it did not have.

`modules/community_treasury.py` opened with `total_impact_pool = 12450.00  # 20% of profit
pool` and reported `profit_share_percent: 20.0`. There is no profit, no pool, and nobody has
committed to sharing one, so a fresh install told a community it had twelve thousand euros to
allocate. Money was floats. Proposals defaulted to 500.0 for "charity" by "Community Member".

Voting was the worst of it: `vote_proposal` incremented a counter and recorded nobody, so one
caller posting five times flipped a proposal to "approved" — and an approved grant was
subtracted from the imaginary balance, which is the point where somebody plans around it.

`/dao/community-treasury` already answered this honestly. Two implementations that contradict
each other are worse than either, so these route through the same module.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def world(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


def test_the_module_that_invented_the_pool_is_gone():
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("modules.community_treasury")


def test_there_is_no_balance_and_no_profit_share(world):
    client, people = world
    out = client.get("/v1/treasury/status?city=Lisbon", headers=people["ana"]["h"]).json()
    assert out["pool"] is None
    assert out["profit_share"] is None
    assert out["money_moved"] is False
    assert out["no_pool"]
    for gone in ("treasury_balance", "total_disbursed", "profit_share_percent"):
        assert gone not in out


def test_no_invented_figure_survives(world):
    client, people = world
    body = client.get("/v1/treasury/status?city=Lisbon", headers=people["ana"]["h"]).text
    for invented in ("12450", "12,450", "20.0", "500.0", "Community Member"):
        assert invented not in body


def test_an_ask_is_recorded_in_whole_cents_and_approves_nothing(world):
    client, people = world
    made = client.post("/v1/treasury/proposals",
                       json={"city": "Lisbon", "project": "Repair café tools",
                             "amount": "120.50", "currency": "EUR"},
                       headers=people["ana"]["h"])
    assert made.status_code == 200, made.text
    out = made.json()
    assert out["amount_cents"] == 12050
    assert out["approved"] is False
    assert out["money_moved"] is False

    listed = client.get("/v1/treasury/status?city=Lisbon",
                        headers=people["bruno"]["h"]).json()
    assert listed["count"] == 1
    # Per-currency rows, never one summed number: adding across currencies is the
    # arithmetic the tab refuses too.
    assert [(r["currency"], r["amount_cents"]) for r in listed["asked_for"]] == [("EUR", 12050)]
    assert listed["pool"] is None


def test_a_proposal_needs_a_project_and_an_amount(world):
    """It defaulted both, so an empty body proposed a 500.00 charity grant."""
    client, people = world
    assert client.post("/v1/treasury/proposals", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).status_code == 400
    assert client.post("/v1/treasury/proposals",
                       json={"city": "Lisbon", "project": "Tools"},
                       headers=people["ana"]["h"]).status_code == 400


def test_voting_refuses_rather_than_counting_nobody(world):
    """Five posts from one caller marked a grant approved, and approval funded nothing."""
    client, people = world
    res = client.post("/v1/treasury/vote", json={"proposal_id": "anything"},
                      headers=people["ana"]["h"])
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail["available"] is False
    assert detail["money_moved"] is False
    assert detail["why"]


def test_the_withdraw_route_the_refusal_names_exists(world):
    """The refusal points at DELETE /v1/community/micro-grants. A suggestion naming a route
    that does not exist is the same dead-link defect in prose."""
    client, people = world
    made = client.post("/v1/treasury/proposals",
                       json={"city": "Lisbon", "project": "Tools", "amount": "40.00"},
                       headers=people["ana"]["h"]).json()

    theirs = client.request("DELETE", "/v1/community/micro-grants",
                            json={"proposal_id": made["proposal_id"]},
                            headers=people["bruno"]["h"])
    assert theirs.status_code == 400          # only the proposer may withdraw it

    mine = client.request("DELETE", "/v1/community/micro-grants",
                          json={"proposal_id": made["proposal_id"]},
                          headers=people["ana"]["h"])
    assert mine.status_code == 200
    assert mine.json()["withdrawn"] is True
    assert client.get("/v1/treasury/status?city=Lisbon",
                      headers=people["ana"]["h"]).json()["count"] == 0
