"""Rooms: a rendezvous list where three endpoints sold live audio.

`GET /audio/lounge-spaces` listed two `LIVE_NOW` lounges with 8 and 14 listeners and
speakers called Alex, Elena R. and Marcus T. `POST /spaces/audio` answered `created: True`
with a room_url on a host this deployment does not serve, and stored nothing.
`POST /voice/crew-huddle` reported a codec, 18ms latency and two people at two bearings.

There is no audio transport here, so these pin the room that is left when the sound is
taken away — and that every response says there is no sound.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import rooms
from modules.crews import crews

PW = "correct-horse-battery"

INVENTED = ("listeners", "speakers", "active_speakers", "codec", "latency_ms",
            "noise_suppression", "room_url", "status", "LIVE_NOW")


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


# ---- the module --------------------------------------------------------------

def test_a_room_holds_the_people_who_actually_joined(graph):
    opened = rooms.open_room(graph, title="Film chat", account_id="acct-1",
                             handle="ana", city="Lisbon")
    assert opened["members"] == 1 and opened["audio"] is False

    rooms.join(graph, opened["room_id"], account_id="acct-2", handle="bruno")
    listed = rooms.listing(graph, city="Lisbon", viewer_id="acct-2")
    room = listed["rooms"][0]
    assert room["member_count"] == 2
    assert {member["handle"] for member in room["members"]} == {"ana", "bruno"}
    assert room["you_are_in"] is True


def test_every_answer_says_there_is_no_audio(graph):
    opened = rooms.open_room(graph, title="Film chat", account_id="acct-1", city="Lisbon")
    joined = rooms.join(graph, opened["room_id"], account_id="acct-2")
    listed = rooms.listing(graph, city="Lisbon")
    assert opened["audio"] is False and joined["audio"] is False
    assert listed["audio"] is False and listed["rooms"][0]["audio"] is False
    # Worded out of the capability table, so the status page and this cannot disagree.
    from modules.platform import capabilities
    assert capabilities.UNAVAILABLE[capabilities.AUDIO]["why"].lower() in \
        rooms.NO_AUDIO.lower()


def test_a_room_needs_a_title_and_somewhere_to_live(graph):
    with pytest.raises(rooms.RoomError):
        rooms.open_room(graph, title="", account_id="acct-1", city="Lisbon")
    with pytest.raises(rooms.RoomError):
        rooms.open_room(graph, title="Film chat", account_id="acct-1")


def test_leaving_as_the_opener_closes_it(graph):
    opened = rooms.open_room(graph, title="Film chat", account_id="acct-1", city="Lisbon")
    rooms.join(graph, opened["room_id"], account_id="acct-2")
    out = rooms.leave(graph, opened["room_id"], account_id="acct-1")
    assert out["closed"] is True
    assert rooms.listing(graph, city="Lisbon")["empty"] is True


@pytest.fixture
def two_accounts(graph):
    """Real accounts: crew membership is checked against them, not against a string."""
    from gateway import accounts
    return (accounts.register(graph, "ana", PW)["account_id"],
            accounts.register(graph, "bruno", PW)["account_id"])


def test_a_crew_room_is_private_to_the_crew(graph, two_accounts):
    ana, bruno = two_accounts
    crew_id = crews.create(graph, "Film crew", city="Lisbon", admin_id=ana)["id"]
    opened = rooms.open_room(graph, title="Tonight", account_id=ana, crew_id=crew_id)
    assert opened["crew_id"] == crew_id

    with pytest.raises(rooms.RoomError):
        rooms.open_room(graph, title="Nope", account_id=bruno, crew_id=crew_id)
    with pytest.raises(rooms.RoomError):
        rooms.join(graph, opened["room_id"], account_id=bruno)
    with pytest.raises(rooms.RoomError):
        rooms.listing(graph, crew_id=crew_id, viewer_id=bruno)


def test_a_city_room_is_not_listed_as_a_crew_room(graph, two_accounts):
    ana, _ = two_accounts
    crew_id = crews.create(graph, "Film crew", city="Lisbon", admin_id=ana)["id"]
    rooms.open_room(graph, title="City one", account_id=ana, city="Lisbon")
    assert rooms.listing(graph, crew_id=crew_id, viewer_id=ana)["empty"] is True


# ---- over HTTP ---------------------------------------------------------------

def test_the_lounge_list_starts_empty_and_names_nobody(world):
    client, people = world
    res = client.get("/v1/audio/lounge-spaces?city=Lisbon", headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["rooms"] == [] and body["empty"] is True and body["audio"] is False
    for invented in ("elena", "marcus", "alex", "miradouro", "listeners"):
        assert invented not in res.text.lower()


def test_opening_a_room_then_joining_it_from_another_account(world):
    client, people = world
    opened = client.post("/v1/spaces/audio",
                         json={"city": "Lisbon", "title": "Film chat"},
                         headers=people["ana"]["h"])
    assert opened.status_code == 200
    room_id = opened.json()["room_id"]
    assert opened.json()["audio"] is False

    joined = client.post("/v1/spaces/audio/join", json={"room_id": room_id},
                         headers=people["bruno"]["h"])
    assert joined.status_code == 200 and joined.json()["members"] == 2

    listed = client.get("/v1/audio/lounge-spaces?city=Lisbon", headers=people["bruno"]["h"])
    room = listed.json()["rooms"][0]
    assert room["title"] == "Film chat" and room["member_count"] == 2
    assert room["you_are_in"] is True

    left = client.post("/v1/spaces/audio/leave", json={"room_id": room_id},
                       headers=people["bruno"]["h"])
    assert left.status_code == 200 and left.json()["members"] == 1


def test_no_room_url_is_minted_for_a_host_this_app_does_not_serve(world):
    client, people = world
    res = client.post("/v1/spaces/audio", json={"city": "Lisbon", "title": "Film chat"},
                      headers=people["ana"]["h"])
    text = res.text
    assert "http://" not in text and "https://" not in text
    for invented in INVENTED:
        assert invented not in text


def test_a_huddle_needs_a_crew_you_are_in(world):
    client, people = world
    crew = client.post("/v1/crews", json={"name": "Film crew", "city": "Lisbon"},
                       headers=people["ana"]["h"])
    crew_id = crew.json()["id"]

    mine = client.post("/v1/voice/crew-huddle",
                       json={"crew_id": crew_id, "title": "Tonight"},
                       headers=people["ana"]["h"])
    assert mine.status_code == 200 and mine.json()["audio"] is False

    theirs = client.post("/v1/voice/crew-huddle",
                         json={"crew_id": crew_id, "title": "Tonight"},
                         headers=people["bruno"]["h"])
    assert theirs.status_code == 400
    for invented in ("hamish", "catriona", "opus", "spatial"):
        assert invented not in theirs.text.lower()


def test_a_huddle_with_no_crew_is_refused_rather_than_answered(world):
    client, people = world
    res = client.post("/v1/voice/crew-huddle", json={"title": "Tonight"},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
