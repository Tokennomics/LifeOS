"""The badge that rated you before you had done anything.

`/trust/badge` counted attended outings correctly, then wrapped them in things nobody had
checked: a `reliability_score` of `min(99, 85 + attended * 2)`, so a brand-new account read
**85%** and no amount of not turning up could lower it; a tier that was that number renamed;
and a `share_text` calling it "LifeOS **Verified** Real-World Meeter", beside a button
offering to paste it into an Instagram or Tinder bio. The person reading it there has no way
to know that nothing was verified.

The count stays, because it was the one true thing in the response.
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
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_a_new_account_has_attended_nothing(world):
    """It read 85% Reliability, Bronze Meeter, on an account one second old."""
    client, headers = world
    out = client.get("/v1/trust/badge", headers=headers).json()
    assert out["attended"] == 0
    assert out["empty"] is True
    assert out["suggestion"]


def test_nothing_is_scored_or_tiered(world):
    client, headers = world
    out = client.get("/v1/trust/badge", headers=headers).json()
    assert out["scored"] is False
    assert out["verified"] is False
    for gone in ("reliability_score", "tier", "verified_meets"):
        assert gone not in out


def test_no_percentage_survives_anywhere_in_the_body(world):
    """The score's every disguise was a percent sign."""
    client, headers = world
    body = client.get("/v1/trust/badge", headers=headers).text
    assert "%" not in body


def test_the_share_text_does_not_claim_a_verification(world):
    """It is written to be pasted where a stranger reads it, so it has to carry its own
    provenance: self-recorded, by the person it is about."""
    client, headers = world
    out = client.get("/v1/trust/badge", headers=headers).json()
    share = out["share_text"].lower()
    assert "verified" not in share or "not verified" in share
    assert "self-recorded" in share
    assert out["not_verification"]


def test_it_names_the_caller_and_never_a_default_person(world):
    """The handle defaulted to "robert", so an unauthenticated request got a named
    person's card."""
    client, headers = world
    assert client.get("/v1/trust/badge", headers=headers).json()["handle"] == "ana"
    anon = client.get("/v1/trust/badge")
    if anon.status_code == 200:
        assert anon.json()["handle"] != "robert"


def test_the_count_is_a_count(world):
    """Two outings marked attended read as two, with no adjective attached."""
    client, headers = world
    for title in ("Bouldering", "Coffee crawl"):
        made = client.post("/v1/convoy/event",
                           json={"title": title, "start": "2026-10-01T18:00:00Z"},
                           headers=headers)
        assert made.status_code == 200, made.text
        event_id = made.json()["event_id"]
        marked = client.post("/v1/convoy/attended", json={"event_id": event_id},
                             headers=headers)
        assert marked.status_code == 200, marked.text

    out = client.get("/v1/trust/badge", headers=headers).json()
    assert out["attended"] == 2
    assert out["empty"] is False
    assert "2 outings" in out["share_text"]
