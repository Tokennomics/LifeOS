"""Ambassadors, micro-grants and the treasury that does not exist.

`GET /community/ambassadors` was a launch heatmap — Lisbon 1,420 members, Barcelona "85%, 15
more to unlock" — with every number a constant and nothing behind the lock.
`POST /community/micro-grants` answered `grant_voted: True`, `FUNDED_AND_APPROVED`, a
"€1,450.00 community fund pool" and 48 votes for any project string.
`POST /dao/community-treasury` reported a £12,450 balance and three proposals passing at
88%, 76% and "FUNDED", under "Quadratic Citizen Voting".

None of that existed. These pin the rows that do.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.community import ambassadors, grants

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


# ---- ambassadors, the module -------------------------------------------------

def test_only_people_who_opted_in_are_listed(graph):
    assert ambassadors.listing(graph, "Lisbon")["empty"] is True
    ambassadors.opt_in(graph, "Lisbon", account_id="acct-1", handle="ana",
                       note="ask me about the trams")
    out = ambassadors.listing(graph, "Lisbon", viewer_id="acct-1")
    assert out["count"] == 1
    assert out["ambassadors"][0]["handle"] == "ana"
    assert out["ambassadors"][0]["note"] == "ask me about the trams"
    assert out["you_are_one"] is True
    assert out["vetted"] is False


def test_volunteering_twice_is_one_row(graph):
    ambassadors.opt_in(graph, "Lisbon", account_id="acct-1", handle="ana")
    ambassadors.opt_in(graph, "Lisbon", account_id="acct-1", handle="ana", days=30)
    assert ambassadors.listing(graph, "Lisbon")["count"] == 1


def test_standing_down_removes_you_at_once(graph):
    ambassadors.opt_in(graph, "Lisbon", account_id="acct-1", handle="ana")
    out = ambassadors.opt_out(graph, "Lisbon", account_id="acct-1")
    assert out["was_listed"] is True
    assert ambassadors.listing(graph, "Lisbon")["empty"] is True


def test_one_city_is_not_another(graph):
    ambassadors.opt_in(graph, "Lisbon", account_id="acct-1", handle="ana")
    assert ambassadors.listing(graph, "Porto")["empty"] is True


def test_a_volunteer_row_needs_a_city_and_an_account(graph):
    with pytest.raises(ambassadors.AmbassadorError):
        ambassadors.opt_in(graph, "", account_id="acct-1")
    with pytest.raises(ambassadors.AmbassadorError):
        ambassadors.opt_in(graph, "Lisbon", account_id="")


# ---- grants, the module ------------------------------------------------------

def test_a_proposal_is_stored_in_whole_cents(graph):
    made = grants.propose(graph, "Lisbon", project="A bench", amount=120.55,
                          account_id="acct-1", handle="ana")
    assert made["amount_cents"] == 12055 and made["amount"] == 120.55
    assert made["approved"] is False and made["money_moved"] is False

    out = grants.listing(graph, "Lisbon")
    assert out["count"] == 1
    assert out["asked_for"] == [{"currency": "EUR", "amount": 120.55,
                                 "amount_cents": 12055}]
    assert out["pool"] is None


def test_currencies_are_totalled_apart(graph):
    grants.propose(graph, "Lisbon", project="A bench", amount=10,
                   account_id="acct-1")
    grants.propose(graph, "Lisbon", project="A sign", amount=5, currency="GBP",
                   account_id="acct-1")
    totals = {row["currency"]: row["amount_cents"]
              for row in grants.listing(graph, "Lisbon")["asked_for"]}
    assert totals == {"EUR": 1000, "GBP": 500}


def test_a_proposal_needs_a_project_and_an_amount(graph):
    with pytest.raises(grants.GrantError):
        grants.propose(graph, "Lisbon", project="", amount=10, account_id="acct-1")
    with pytest.raises(grants.GrantError):
        grants.propose(graph, "Lisbon", project="A bench", amount=None,
                       account_id="acct-1")
    with pytest.raises(grants.GrantError):
        grants.propose(graph, "Lisbon", project="A bench", amount=-5,
                       account_id="acct-1")


def test_nothing_in_the_module_can_approve_one(graph):
    """There is no approve function, and every response carries the two falses. Approval
    would mean somebody holding money, which no part of this deployment does."""
    assert not [name for name in dir(grants) if "approve" in name]
    made = grants.propose(graph, "Lisbon", project="A bench", amount=10,
                          account_id="acct-1")
    listed = grants.listing(graph, "Lisbon")
    assert made["approved"] is False and made["money_moved"] is False
    assert listed["proposals"][0]["approved"] is False
    assert listed["money_moved"] is False


# ---- over HTTP ---------------------------------------------------------------

def test_the_ambassador_list_starts_empty_and_names_no_city(world):
    client, people = world
    res = client.get("/v1/community/ambassadors?city=Lisbon", headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.json()["empty"] is True and res.json()["ambassadors"] == []
    for invented in ("tokyo", "barcelona", "berlin", "1420", "85%", "launching_soon"):
        assert invented not in res.text.lower()


def test_opting_in_puts_you_on_the_list_and_opting_out_takes_you_off(world):
    client, people = world
    opted = client.post("/v1/community/ambassadors",
                        json={"city": "Lisbon", "note": "ask me about the trams"},
                        headers=people["ana"]["h"])
    assert opted.status_code == 200 and opted.json()["ambassador"] is True

    seen = client.get("/v1/community/ambassadors?city=Lisbon",
                      headers=people["bruno"]["h"])
    assert [row["handle"] for row in seen.json()["ambassadors"]] == ["ana"]
    assert seen.json()["vetted"] is False

    client.post("/v1/community/ambassadors", json={"city": "Lisbon", "opt_out": True},
                headers=people["ana"]["h"])
    assert client.get("/v1/community/ambassadors?city=Lisbon",
                      headers=people["bruno"]["h"]).json()["empty"] is True


def test_a_grant_is_a_proposal_and_says_so_twice(world):
    client, people = world
    res = client.post("/v1/community/micro-grants",
                      json={"city": "Lisbon", "project": "A bench", "amount": 120.55},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["approved"] is False and body["money_moved"] is False
    assert body["amount_cents"] == 12055
    for invented in ("grant_voted", "votes_count", "funded", "community_fund_pool"):
        assert invented not in res.text.lower()


def test_a_grant_without_an_amount_is_refused_rather_than_funded(world):
    client, people = world
    res = client.post("/v1/community/micro-grants",
                      json={"city": "Lisbon", "project": "A bench"},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "1,450" not in res.text and "1450" not in res.text


def test_proposals_are_listable_by_everybody_in_the_city(world):
    client, people = world
    client.post("/v1/community/micro-grants",
                json={"city": "Lisbon", "project": "A bench", "amount": 20},
                headers=people["ana"]["h"])
    listed = client.post("/v1/community/micro-grants", json={"city": "Lisbon"},
                         headers=people["bruno"]["h"])
    assert listed.status_code == 200
    assert [row["project"] for row in listed.json()["proposals"]] == ["A bench"]
    assert listed.json()["asked_for"][0]["amount_cents"] == 2000


def test_the_treasury_says_it_does_not_exist_and_shows_what_does(world):
    """The alternative — summing what the shared tabs hold — was rejected: a tab entry is a
    private debt between two people, and a pile of what people owe each other is not money a
    community can spend."""
    client, people = world
    client.post("/v1/community/micro-grants",
                json={"city": "Lisbon", "project": "A bench", "amount": 20},
                headers=people["ana"]["h"])

    res = client.post("/v1/dao/community-treasury", json={"city": "Lisbon"},
                      headers=people["bruno"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False and body["money_moved"] is False
    assert body["why"] and body["needs"]
    assert body["proposal_count"] == 1
    assert body["asked_for"][0]["amount_cents"] == 2000
    for invented in ("12,450", "12450", "prop-041", "quadratic", "votes_for",
                     "passing_88"):
        assert invented not in res.text.lower()


def test_the_treasury_borrows_the_payments_wording_rather_than_writing_its_own(world):
    from modules.platform import capabilities
    client, people = world
    res = client.post("/v1/dao/community-treasury", json={"city": "Lisbon"},
                      headers=people["ana"]["h"])
    why = capabilities.UNAVAILABLE[capabilities.PAYMENTS]["why"]
    assert why in res.json()["why"]
