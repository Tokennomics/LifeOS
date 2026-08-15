"""The tab over HTTP: two accounts, one dinner, and the same number on both screens.

The four endpoints these replace are the worst props in the repo, because they were about
money between friends. `/ledger/quick-split` handed back a `revolut.me` link for an account
nobody had connected. `/ledger/settle-up` told a brand-new account it owed €22.50 to two
people who do not exist. `/ledger/gift-coffee` returned the same voucher code every time.

The assertions that matter most are the negative ones: no payment link, no voucher, and
nothing anywhere claiming money moved.
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
def table(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno", "carla"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


def test_a_split_lands_on_both_tabs(table):
    client, people = table
    out = client.post("/v1/ledger/quick-split",
                      json={"amount": 60, "participants": [people["bruno"]["id"],
                                                           people["carla"]["id"]],
                            "title": "tapas"},
                      headers=people["ana"]["h"]).json()
    assert out["split"] is True
    assert out["your_share"] == 20.0

    hers = client.get("/v1/ledger/tab", headers=people["ana"]["h"]).json()
    assert hers["owed_to_you"] == {"EUR": 40.0}
    his = client.get("/v1/ledger/tab", headers=people["bruno"]["h"]).json()
    assert his["you_owe"] == {"EUR": 20.0}


def test_a_headcount_split_answers_the_maths_and_records_nothing(table):
    """The calculator survives — it just stops pretending it wrote something down."""
    client, people = table
    out = client.post("/v1/ledger/quick-split",
                      json={"amount": 60, "people_count": 4},
                      headers=people["ana"]["h"]).json()
    assert out["recorded"] is False
    assert out["each"] == 15.0
    assert client.get("/v1/ledger/tab",
                      headers=people["ana"]["h"]).json()["empty"] is True


def test_no_payment_link_and_no_voucher_code_anywhere(table):
    client, people = table
    bodies = [
        client.post("/v1/ledger/quick-split",
                    json={"amount": 60, "participants": [people["bruno"]["id"]]},
                    headers=people["ana"]["h"]).json(),
        client.post("/v1/ledger/quick-split", json={"amount": 60, "people_count": 4},
                    headers=people["ana"]["h"]).json(),
        client.post("/v1/ledger/tip",
                    json={"recipient": people["bruno"]["id"], "amount": 3.5},
                    headers=people["ana"]["h"]).json(),
        client.post("/v1/ledger/gift-coffee",
                    json={"recipient": people["bruno"]["id"], "item": "flat white"},
                    headers=people["ana"]["h"]).json(),
    ]
    for body in bodies:
        text = str(body).lower()
        assert "revolut" not in text
        assert "voucher" not in text
        assert "gift-flatwhite" not in text


def test_a_tip_is_owed_not_sent(table):
    client, people = table
    out = client.post("/v1/ledger/tip",
                      json={"recipient": people["bruno"]["id"], "amount": 3.5},
                      headers=people["ana"]["h"]).json()
    assert out["money_moved"] is False
    assert "sent" not in str(out.get("note", "")).lower().split("not sent")[0]
    assert client.get("/v1/ledger/tab",
                      headers=people["bruno"]["h"]).json()["owed_to_you"] == {"EUR": 3.5}


def test_settling_needs_a_real_debt(table):
    """It used to report a settled balance of €22.50 on an account that owed nobody."""
    client, people = table
    res = client.post("/v1/ledger/settle-up",
                      json={"counterparty": people["bruno"]["id"]},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "do not owe" in res.json()["detail"]


def test_settling_clears_the_tab_for_both(table):
    client, people = table
    client.post("/v1/ledger/quick-split",
                json={"amount": 20, "participants": [people["bruno"]["id"]]},
                headers=people["ana"]["h"])
    out = client.post("/v1/ledger/settle-up",
                      json={"counterparty": people["ana"]["id"]},
                      headers=people["bruno"]["h"]).json()
    assert out["clear"] is True
    assert client.get("/v1/ledger/tab", headers=people["ana"]["h"]).json()["empty"] is True
    assert client.get("/v1/ledger/tab", headers=people["bruno"]["h"]).json()["empty"] is True


def test_a_third_party_sees_none_of_the_dinner(table):
    client, people = table
    client.post("/v1/ledger/quick-split",
                json={"amount": 20, "participants": [people["bruno"]["id"]]},
                headers=people["ana"]["h"])
    assert client.get("/v1/ledger/tab",
                      headers=people["carla"]["h"]).json()["empty"] is True
    assert client.get("/v1/ledger/tab/entries",
                      headers=people["carla"]["h"]).json()["empty"] is True


def test_the_history_is_readable_by_both_sides(table):
    client, people = table
    client.post("/v1/ledger/quick-split",
                json={"amount": 20, "participants": [people["bruno"]["id"]],
                      "title": "tapas"},
                headers=people["ana"]["h"])
    for who in ("ana", "bruno"):
        out = client.get("/v1/ledger/tab/entries", headers=people[who]["h"]).json()
        assert out["total"] == 1
        assert out["entries"][0]["note"] == "tapas"


def test_a_split_with_nobody_named_and_no_headcount_is_an_error(table):
    client, people = table
    res = client.post("/v1/ledger/quick-split", json={"amount": 60},
                      headers=people["ana"]["h"])
    assert res.status_code == 400


def test_a_debt_you_never_agreed_to_can_be_rejected(table):
    client, people = table
    out = client.post("/v1/ledger/quick-split",
                      json={"amount": 2000, "participants": ["bruno"]},
                      headers=people["ana"]["h"]).json()
    entry_id = out["entries"][0]["entry_id"]

    listed = client.get("/v1/ledger/tab/entries", headers=people["bruno"]["h"]).json()
    assert listed["entries"][0]["yours_to_dispute"] is True

    client.post("/v1/ledger/tab/dispute", json={"entry_id": entry_id},
                headers=people["bruno"]["h"])
    assert client.get("/v1/ledger/tab", headers=people["bruno"]["h"]).json()["empty"] is True
    assert client.get("/v1/ledger/tab", headers=people["ana"]["h"]).json()["empty"] is True


def test_you_cannot_dispute_a_claim_you_made(table):
    client, people = table
    out = client.post("/v1/ledger/quick-split",
                      json={"amount": 20, "participants": ["bruno"]},
                      headers=people["ana"]["h"]).json()
    res = client.post("/v1/ledger/tab/dispute",
                      json={"entry_id": out["entries"][0]["entry_id"]},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert client.get("/v1/ledger/tab",
                      headers=people["ana"]["h"]).json()["owed_to_you"] == {"EUR": 10.0}


def test_a_stranger_cannot_dispute_somebody_elses_entry(table):
    client, people = table
    out = client.post("/v1/ledger/quick-split",
                      json={"amount": 20, "participants": ["bruno"]},
                      headers=people["ana"]["h"]).json()
    res = client.post("/v1/ledger/tab/dispute",
                      json={"entry_id": out["entries"][0]["entry_id"]},
                      headers=people["carla"]["h"])
    assert res.status_code == 400


def test_an_unsigned_caller_cannot_read_a_tab(table):
    client, _ = table
    assert client.get("/v1/ledger/tab").status_code == 401


def test_people_are_named_by_handle(table):
    """Nobody types a UUID at a dinner table."""
    client, people = table
    client.post("/v1/ledger/quick-split",
                json={"amount": 20, "participants": ["bruno"]},
                headers=people["ana"]["h"])
    assert client.get("/v1/ledger/tab",
                      headers=people["bruno"]["h"]).json()["you_owe"] == {"EUR": 10.0}


def test_a_balance_carries_a_name_a_person_can_read(table):
    """It rendered "762f7110-0962-4523 owes you 30.00" until this was here. Records address
    people by id — ids are stable, handles are not — so the handle is resolved for display."""
    client, people = table
    out = client.post("/v1/ledger/quick-split",
                      json={"amount": 20, "participants": ["bruno"]},
                      headers=people["ana"]["h"]).json()
    assert out["entries"][0]["handle"] == "bruno"
    tab = client.get("/v1/ledger/tab", headers=people["bruno"]["h"]).json()
    assert tab["balances"][0]["handle"] == "ana"
    assert tab["balances"][0]["counterparty"] == people["ana"]["id"]


def test_a_debt_is_never_written_against_a_name_nobody_owns(table):
    """The quiet failure this guards: an entry addressed to a string is invisible to the
    person who supposedly owes it, and can never be settled."""
    client, people = table
    res = client.post("/v1/ledger/quick-split",
                      json={"amount": 20, "participants": ["elena r."]},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "elena r." in res.json()["detail"]
    assert client.get("/v1/ledger/tab",
                      headers=people["ana"]["h"]).json()["empty"] is True
