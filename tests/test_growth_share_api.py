"""The growth endpoints over HTTP.

All five pointed at `connectos.app`, a host this deployment does not serve, for resources
nothing ever created. Two of them attached rewards — 100 karma, a free-coffee voucher, a
year of free VIP, complimentary coffee at partner roasters — from a programme that does not
exist and that nobody has agreed to fund. That is the part worth pinning: a fake link is
embarrassing, a fake promise of something free is a different kind of problem.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app

PW = "correct-horse-battery"
INVENTED = ("connectos.app", "karma", "voucher", "vip", "apple pay",
            "crew-lisbon-8921", "golden-crew-8921", ".png")


def claims(body: dict) -> str:
    """A response with its disclaimers stripped.

    Several of these endpoints now say plainly what they are *not* doing — "no karma and no
    voucher", "there is no Apple Pay split here" — which is worth keeping for whoever reads
    the response, and which makes a whole-body substring search useless. So the negative
    fields (`no_*`, `note`) come out, and what is left is what the endpoint actually claims.
    """
    return str({k: v for k, v in body.items()
                if not k.startswith("no_") and k != "note"}).lower()


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
    made = client.post("/v1/crews", json={"name": "the regulars", "visibility": "private"},
                       headers=people["ana"]["h"]).json()
    return client, people, made.get("id") or made.get("crew_id")


def test_the_viral_invite_is_a_link_that_admits_somebody(world):
    client, people, crew_id = world
    out = client.post("/v1/viral/invite-crew", json={"crew_id": crew_id},
                      headers=people["ana"]["h"]).json()
    assert out["rewards"] is None
    assert out["invite_path"] == f"/invite/{out['token']}"

    joined = client.post("/v1/crews/invite-link/redeem", json={"token": out["token"]},
                         headers=people["bruno"]["h"])
    assert joined.status_code == 200


def test_the_invite_promises_nothing_free(world):
    client, people, crew_id = world
    body = client.post("/v1/viral/invite-crew", json={"crew_id": crew_id},
                       headers=people["ana"]["h"]).json()
    assert body["rewards"] is None
    for invented in INVENTED:
        assert invented not in claims(body)


def test_golden_tickets_are_separate_single_use_links(world):
    client, people, crew_id = world
    out = client.post("/v1/seeding/golden-tickets", json={"crew_id": crew_id, "count": 3},
                      headers=people["ana"]["h"]).json()
    tokens = [t["token"] for t in out["tickets"]]
    assert len(set(tokens)) == 3
    assert out["single_use_each"] is True

    # One person each: the first token admits bruno, and then it is spent.
    assert client.post("/v1/crews/invite-link/redeem", json={"token": tokens[0]},
                       headers=people["bruno"]["h"]).status_code == 200
    assert client.post("/v1/crews/invite-link/redeem", json={"token": tokens[0]},
                       headers=people["bruno"]["h"]).status_code == 400
    # And the other two are still good.
    assert tokens[1] != tokens[0]


def test_the_ticket_count_is_bounded(world):
    client, people, crew_id = world
    for bad in (0, 99, "many"):
        res = client.post("/v1/seeding/golden-tickets",
                          json={"crew_id": crew_id, "count": bad},
                          headers=people["ana"]["h"])
        assert res.status_code == 400


def test_tickets_claim_no_payment_split(world):
    client, people, crew_id = world
    body = client.post("/v1/seeding/golden-tickets", json={"crew_id": crew_id},
                       headers=people["ana"]["h"]).json()
    assert "apple pay" not in claims(body)
    assert "connectos.app" not in claims(body)
    assert "viral_multiplier" not in body


def test_the_share_card_is_drawn_here(world):
    client, people, _ = world
    out = client.post("/v1/viral/social-share",
                      json={"title": "Sunset at the miradouro", "subtitle": "Lisbon"},
                      headers=people["ana"]["h"]).json()
    assert out["svg"].startswith("<svg")
    assert out["rendered_here"] is True
    assert "connectos.app" not in str(out) and ".png" not in str(out)


def test_the_pioneer_pass_is_a_count_with_nothing_attached(world):
    client, people, _ = world
    # ana publishes something in Lisbon, so she is in the count.
    client.post("/v1/synergy/instant-match",
                json={"city": "Lisbon", "interest": "bouldering", "open": True},
                headers=people["ana"]["h"])
    res = client.post("/v1/seeding/pioneer-pass", json={"city": "Lisbon"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    out = res.json()
    assert out["no_perks"]
    assert "your_position" in out
    for invented in INVENTED:
        assert invented not in claims(out)


def test_the_pioneer_pass_needs_a_city(world):
    client, people, _ = world
    assert client.post("/v1/seeding/pioneer-pass", json={},
                       headers=people["ana"]["h"]).status_code == 400


def test_tap_to_synergy_shows_a_code_then_takes_one(world):
    client, people, _ = world
    shown = client.post("/v1/nfc/tap-to-synergy", json={},
                        headers=people["ana"]["h"]).json()
    assert len(shown["code"]) == 6
    assert shown["single_use"] is True

    paired = client.post("/v1/nfc/tap-to-synergy", json={"code": shown["code"]},
                         headers=people["bruno"]["h"]).json()
    assert paired["paired"] is True
    assert paired["peer_handle"] == "ana"


def test_tap_to_synergy_claims_no_protocol_and_no_score(world):
    """It reported a 94% match over an "NFC & Apple NameDrop Ephemeral Handshake" and a
    "zk card exchanged", for any peer string sent."""
    client, people, _ = world
    shown = client.post("/v1/nfc/tap-to-synergy", json={},
                        headers=people["ana"]["h"]).json()
    res = client.post("/v1/nfc/tap-to-synergy", json={"code": shown["code"]},
                      headers=people["bruno"]["h"])
    body = res.json()
    assert not [k for k in body if "score" in k and k != "no_score"]
    assert "zk_card_exchanged" not in res.text
    assert "haptic" not in res.text.lower()
    assert "namedrop" not in res.text.lower()


def test_a_bad_code_is_refused_without_saying_why(world):
    client, people, _ = world
    res = client.post("/v1/nfc/tap-to-synergy", json={"code": "ZZZZZZ"},
                      headers=people["bruno"]["h"])
    assert res.status_code == 400
    assert "not valid" in res.json()["detail"]
