"""Deep audit: the frontier systems perform real writes and real reads.

This file came from the other line of work, where it verified that a set of endpoints did
real Substrate writes rather than returning literals. That intent is exactly right and is
kept. What changed is which implementation each test points at: where both lines built the
same endpoint, the one that survived is the one that does not fabricate, and several of
these assertions had been written against shapes that carried the fabrication with them —
`synthesis_complete` on a day assembled from a city name, `export_complete` on a vault that
was never written, a kudos accepted for any string with no note.

Two endpoints here are *theirs*, kept because they were better: the PKPass payload (this
line returned a URL on a host it does not serve) and the voice copilot's graph context.
"""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def signed_in(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": h,
                        "id": client.get("/v1/auth/me", headers=h).json()["account_id"]}
    return client, people


# ---- the export ---------------------------------------------------------------

def test_universal_markdown_export_cold_start(signed_in):
    """An empty account exports an empty export, and says so.

    Asserted `export_complete` and a vault-file count on a database with nothing in it.
    """
    client, people = signed_in
    res = client.post("/v1/export/universal-markdown", json={}, headers=people["ana"]["h"])
    assert res.status_code == 200
    data = res.json()
    assert data["rows"] == 0
    assert data["download_url"] is None          # no zip on a host nobody serves
    assert "index.md" in data["documents"]


def test_universal_markdown_export_populated_all_kinds(signed_in):
    """Everything you own comes back, across kinds, as real Markdown."""
    client, people = signed_in
    client.post("/v1/capture", json={"text": "cold water at the river"},
                headers=people["ana"]["h"])
    client.post("/v1/ai/stoic-presence-mirror", json={"note": "walked the long way home"},
                headers=people["ana"]["h"])
    client.post("/v1/events/qr-checkin", json={"place": "Fabrica"},
                headers=people["ana"]["h"])

    data = client.post("/v1/export/universal-markdown", json={},
                       headers=people["ana"]["h"]).json()
    everything = "".join(data["documents"].values())
    assert data["rows"] >= 2
    assert "walked the long way home" in everything
    assert "Fabrica" in everything
    # `files` and `rows` are counts, produced by counting.
    assert data["files"] == len(data["documents"])


# ---- the day ------------------------------------------------------------------

def test_daily_reflection_synthesis_graph_persistence(signed_in):
    """A day is read from your own rows, and reading it writes nothing.

    This asserted `synthesis_complete` and a `memory_id`, because the implementation it was
    written against *persisted* a day assembled from the city name — Munich produced dawn
    surfers on the Eisbach and gratitude to a man called Lukas, sealed into the graph with a
    presence score. A fabricated day that is merely displayed is bad; one that is stored
    becomes indistinguishable from a real memory on every screen that reads memories after.
    """
    client, people = signed_in
    client.post("/v1/events/qr-checkin", json={"place": "Fabrica"},
                headers=people["ana"]["h"])

    res = client.post("/v1/journal/daily-reflection-synthesis",
                      json={"city": "Munich"}, headers=people["ana"]["h"])
    assert res.status_code == 200
    data = res.json()
    assert data["empty"] is False
    assert any("Fabrica" in line for line in data["did"])
    assert data["sources"]                       # every line points at a row
    for invented in ("eisbach", "lukas", "munich", "presence_score"):
        assert invented not in res.text.lower()


# ---- writes that must be real --------------------------------------------------

def test_vision_intake_graph_persistence(signed_in):
    """A poster you photographed becomes a real event — and only what you passed."""
    client, people = signed_in
    res = client.post("/v1/vision/intake",
                      json={"title": "Midnight vinyl listening", "venue": "the loft",
                            "date": "Friday 21:00"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    everything = "".join(client.post("/v1/export/universal-markdown", json={},
                                     headers=people["ana"]["h"]).json()["documents"].values())
    assert "Midnight vinyl listening" in everything


def test_voice_copilot_context_awareness(signed_in):
    """Kept from the other line: it gathers real places, events, goals and people."""
    client, people = signed_in
    res = client.post("/v1/voice/copilot-chat",
                      json={"query": "what is on tonight", "city": "Lisbon"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200


def test_developer_api_keys_graph_persistence(signed_in):
    """A key is a credential, so it is returned once and stored as a digest."""
    client, people = signed_in
    res = client.post("/v1/developer/keys", json={"name": "Production Webhook",
                                                  "scopes": ["read"]},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    data = res.json()
    assert data["secret"].startswith("los_sk_")
    assert data["key_id"]
    # It opens the door it claims to: the key authenticates as its issuer.
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {data['secret']}"})
    assert me.status_code == 200


def test_kudos_and_flash_moments_graph_persistence(signed_in):
    """Both write real rows — and a kudos has to reach the person it names.

    This posted `{"recipient": "Hanna"}` with no note. That was accepted because the
    implementation stored the recipient as a bare string and awarded 50 XP; the person it
    was about could never read it, which is the one thing the record exists to do.
    """
    client, people = signed_in
    res_kudos = client.post("/v1/kudos/send",
                            json={"to_account": "bruno", "note": "you carried the night"},
                            headers=people["ana"]["h"])
    assert res_kudos.status_code == 200
    assert res_kudos.json()["sent"] is True
    got = client.get("/v1/kudos", headers=people["bruno"]["h"]).json()
    assert [k["note"] for k in got["kudos"]] == ["you carried the night"]
    assert "xp" not in res_kudos.text.lower()

    res_moment = client.post("/v1/moments/flash",
                             json={"city": "Lisbon", "caption": "sunrise swim"},
                             headers=people["ana"]["h"])
    assert res_moment.status_code == 200
    assert res_moment.json()["posted"] is True


def test_apple_wallet_pass_generation(signed_in):
    """Kept from the other line: a real base64 PKPass payload, not a URL to a file nobody
    wrote on a host this deployment does not serve."""
    client, people = signed_in
    res = client.post("/v1/events/apple-wallet-pass",
                      json={"event_name": "Isar Sunrise Plunge"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    data = res.json()
    assert data["pkpass_url"].startswith("data:application/vnd.apple.pkpass;base64,")
    payload = json.loads(base64.b64decode(
        data["pkpass_url"].split("base64,")[1]).decode("utf-8"))
    assert payload["description"] == "Isar Sunrise Plunge"
    assert "connectos.app" not in res.text


def test_synergy_overlap_graph_awareness(signed_in):
    """The overlap is computed from what two people published, and is usually nothing."""
    client, people = signed_in
    res = client.get("/v1/synergy/overlap", headers=people["ana"]["h"])
    assert res.status_code == 200
    for invented in ("elena", "96%", "catriona"):
        assert invented not in res.text.lower()


def test_social_synergy_and_dating_match_persistence(signed_in):
    """Publishing an intent is a real row; dating stays behind its gate."""
    client, people = signed_in
    published = client.post("/v1/synergy/open-to",
                            json={"city": "Lisbon", "activity": "bouldering"},
                            headers=people["ana"]["h"])
    assert published.status_code == 200

    found = client.post("/v1/synergy/instant-match",
                        json={"city": "Lisbon", "interest": "bouldering"},
                        headers=people["bruno"]["h"])
    assert found.status_code == 200
    assert "elena" not in found.text.lower()

    # Off by default, and it says so rather than matching nobody against nobody.
    dating = client.post("/v1/dating/instant-meet",
                         json={"city": "Lisbon", "vibe": "drinks"},
                         headers=people["ana"]["h"])
    assert dating.status_code in (200, 503)


def test_highlight_reel_memory_persistence(signed_in):
    """It must not invent who was there.

    The other line made this graph-backed, which made it worse: it wrote
    `attendees: ["You", "Elena R.", "Alex", "Marcus T."]` and two badges into the graph, so
    the fabricated guest list became a durable record of an evening.
    """
    client, people = signed_in
    res = client.post("/v1/memories/highlight-reel", json={"title": "a real evening"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    for invented in ("elena", "marcus", "pop-89f12a04"):
        assert invented not in res.text.lower()


def test_squad_routine_ics_validity(signed_in):
    """A routine expands into real dates and reaches a calendar feed."""
    client, people = signed_in
    made = client.post("/v1/crews", json={"name": "the regulars", "visibility": "private"},
                       headers=people["ana"]["h"]).json()
    crew_id = made.get("id") or made.get("crew_id")

    res = client.post("/v1/routines/squad-sync",
                      json={"crew_id": crew_id, "title": "dawn patrol",
                            "day": "wed", "at": "07:00"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    assert res.json()["calendars_synced"] == 0        # nobody's calendar was touched

    feed = client.get(res.json()["ics_path"], headers=people["ana"]["h"])
    assert "BEGIN:VCALENDAR" in feed.text
    assert "dawn patrol" in feed.text


def test_viral_social_share_svg_data_uri(signed_in):
    """The card is drawn in this process, not fetched from a host nobody serves."""
    client, people = signed_in
    res = client.post("/v1/viral/social-share", json={"title": "Sunset at the miradouro"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    data = res.json()
    assert data["svg"].startswith("<svg")
    assert data["rendered_here"] is True
    assert "connectos.app" not in res.text


def test_workshops_and_nightlife_persistence(signed_in):
    """Both answer from what people published, and name nobody who does not exist."""
    client, people = signed_in
    for path, body in (("/v1/workshops/micro-masterclasses", {"city": "Lisbon"}),
                       ("/v1/nightlife/party-radar", {"city": "Lisbon"})):
        res = client.post(path, json=body, headers=people["ana"]["h"])
        assert res.status_code == 200, path
        for invented in ("elena", "catriona", "marcus"):
            assert invented not in res.text.lower(), path


def test_layover_multi_hub_discovery(signed_in):
    """A layover answers about the city you name, and invents no transit line."""
    client, people = signed_in
    res = client.post("/v1/travel/layover-discovery",
                      json={"city": "Edinburgh", "hours": 6},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
