"""City chat — the first genuinely public room in LifeOS.

A crew has an admission policy and an admin. A city room has neither: anyone signed in can
read and post, to strangers, about where they physically are tonight. So most of this file
is not about messages arriving — it is about the room being a safe thing to walk into.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.city import chat

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def room(cfg):
    """Three travellers who have never met, on one instance."""
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno", "mallory"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {
            "h": headers,
            "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


def _say(client, who, text, city="Lisbon"):
    return client.post("/v1/city/chat", headers=who["h"], json={"city": city, "text": text})


def _read(client, who, city="Lisbon"):
    return client.get(f"/v1/city/chat?city={city}", headers=who["h"]).json()


# ---- the point of the feature -------------------------------------------------

def test_strangers_can_talk_without_knowing_each_other(room):
    """The whole reason this exists: every other social feature starts from a connection you
    already have. You land somewhere at 6pm knowing nobody and there is a room."""
    client, people = room
    assert _say(client, people["ana"], "Anyone climbing tomorrow?").status_code == 200
    assert _say(client, people["bruno"], "I'm in — Cascais?").status_code == 200

    seen = _read(client, people["mallory"])["messages"]
    assert [m["text"] for m in seen] == ["Anyone climbing tomorrow?", "I'm in — Cascais?"]
    assert [m["author_handle"] for m in seen] == ["ana", "bruno"]


def test_a_room_is_shared_not_per_account(graph):
    """Owner-scoped rows would mean everybody talking to themselves — the exact bug that made
    every dating match return `is_mutual: False`. Messages are system-owned."""
    from substrate import SYSTEM_OWNER
    chat.post(graph, "Lisbon", "hello", author_id="acct-1", author_handle="ana")

    from substrate.graph import Graph
    rows = Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(
        "t", {"content:read"}).find_entities("content", {"type": chat.RECORD}, limit=5)
    assert len(rows) == 1 and rows[0]["owner_id"] == SYSTEM_OWNER


@pytest.mark.parametrize("spelling", ["Lisbon", "lisbon", " LISBON ", "lisbon "])
def test_one_city_is_one_room(room, spelling):
    """Split rooms are empty rooms. `São Paulo` and `sao-paulo` must not diverge either."""
    client, people = room
    _say(client, people["ana"], "hello", city="Lisbon")
    assert len(_read(client, people["bruno"], city=spelling)["messages"]) == 1


def test_accented_city_names_land_in_one_room(graph):
    assert chat.slug("São Paulo") == chat.slug("sao paulo") == "sao-paulo"


def test_the_rooms_list_shows_where_people_are_without_saying_who(room):
    """Discoverability without a presence list: a room you have to guess the name of is a
    room nobody enters, but 'who is in Lisbon tonight' is not ours to publish."""
    client, people = room
    _say(client, people["ana"], "hi", city="Lisbon")
    _say(client, people["bruno"], "hi", city="Lisbon")
    _say(client, people["mallory"], "hi", city="Porto")

    rooms = {r["city"]: r for r in client.get("/v1/city/rooms",
                                              headers=people["ana"]["h"]).json()["rooms"]}
    assert rooms["lisbon"]["messages"] == 2 and rooms["lisbon"]["voices"] == 2
    assert rooms["porto"]["messages"] == 1
    assert "author_id" not in repr(rooms), "a rooms list must not name anyone"


# ---- posting as somebody else -------------------------------------------------

def test_you_cannot_post_as_another_account(room):
    """The most obvious attack on a public room, and the one the crew takeover was."""
    client, people = room
    attack = client.post("/v1/city/chat", headers=people["mallory"]["h"], json={
        "city": "Lisbon", "text": "Ana says: meet me alone at midnight",
        "author_id": people["ana"]["id"], "user_id": people["ana"]["id"]})
    # The body's ids are ignored outright rather than honoured.
    if attack.status_code == 200:
        posted = _read(client, people["ana"])["messages"][-1]
        assert posted["author_handle"] == "mallory"
        assert posted["author_id"] == people["mallory"]["id"]


def test_the_handle_shown_is_the_session_s(room):
    client, people = room
    _say(client, people["bruno"], "hello")
    assert _read(client, people["ana"])["messages"][-1]["author_handle"] == "bruno"


def test_reading_and_posting_need_a_session(cfg):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    assert client.get("/v1/city/chat?city=Lisbon").status_code == 401
    assert client.post("/v1/city/chat",
                       json={"city": "Lisbon", "text": "hi"}).status_code == 401


# ---- muting: personal, silent, one-sided --------------------------------------

def test_muting_hides_someone_for_you_only(room):
    """Nobody needs permission to stop reading someone, and the muted person is never told —
    being told is what turns 'I would rather not' into a confrontation."""
    client, people = room
    _say(client, people["mallory"], "unpleasant thing")
    _say(client, people["bruno"], "climbing at six")

    client.post("/v1/city/chat/mute", headers=people["ana"]["h"],
                json={"target_id": people["mallory"]["id"]})

    mine = _read(client, people["ana"])
    assert [m["text"] for m in mine["messages"]] == ["climbing at six"]
    assert mine["muted"] == 1
    # ...and everyone else's room is untouched.
    assert len(_read(client, people["bruno"])["messages"]) == 2


def test_a_mute_list_is_private_to_its_owner(room):
    """It lives in the muter's own slice. Who you have muted is a statement about you."""
    client, people = room
    client.post("/v1/city/chat/mute", headers=people["ana"]["h"],
                json={"target_id": people["mallory"]["id"]})
    assert chat.muted_by(
        client.app.state.graph, people["mallory"]["id"]) == set()


def test_muting_is_reversible_and_idempotent(room):
    client, people = room
    target = {"target_id": people["mallory"]["id"]}
    assert client.post("/v1/city/chat/mute", headers=people["ana"]["h"],
                       json=target).json()["already"] is False
    assert client.post("/v1/city/chat/mute", headers=people["ana"]["h"],
                       json=target).json()["already"] is True

    _say(client, people["mallory"], "hello again")
    assert _read(client, people["ana"])["messages"] == []
    client.request("DELETE", "/v1/city/chat/mute", headers=people["ana"]["h"], json=target)
    assert len(_read(client, people["ana"])["messages"]) == 1


def test_you_cannot_mute_yourself(room):
    client, people = room
    assert client.post("/v1/city/chat/mute", headers=people["ana"]["h"],
                       json={"target_id": people["ana"]["id"]}).status_code == 400


# ---- taking back what you said -------------------------------------------------

def test_you_can_remove_your_own_message(room):
    client, people = room
    posted = _say(client, people["ana"], "wrong room, sorry").json()
    assert client.delete(f"/v1/city/chat/message/{posted['message_id']}",
                         headers=people["ana"]["h"]).status_code == 200
    assert _read(client, people["bruno"])["messages"] == []


def test_you_cannot_remove_somebody_else_s(room):
    """Rows are system-owned, so `delete_entity`'s owner check does not apply here and
    authorship has to be checked explicitly. If it were not, anyone could clear the room."""
    client, people = room
    posted = _say(client, people["ana"], "meeting at eight").json()
    assert client.delete(f"/v1/city/chat/message/{posted['message_id']}",
                         headers=people["mallory"]["h"]).status_code == 400
    assert len(_read(client, people["bruno"])["messages"]) == 1


# ---- reports go to the operator, never to the room ----------------------------

def test_a_report_is_invisible_to_the_person_reported(room):
    """The second-round finding, in a new place: the reported person could read the report
    about himself — the reporter's id and her account of what happened — and dismiss it."""
    client, people = room
    posted = _say(client, people["mallory"], "something threatening").json()
    filed = client.post("/v1/city/chat/report", headers=people["ana"]["h"], json={
        "message_id": posted["message_id"], "reason": "followed me from the bar"})
    assert filed.status_code == 200

    assert client.get("/v1/city/chat/reports",
                      headers=people["mallory"]["h"]).status_code == 403
    assert client.get("/v1/city/chat/reports",
                      headers=people["ana"]["h"]).status_code == 403


def test_an_operator_sees_the_report_with_its_evidence(cfg):
    """Messages expire in a week; a report that outlives its evidence cannot be acted on, so
    the text is copied at report time."""
    app_cfg = {**cfg, "gateway": {**cfg.get("gateway", {}), "auth_token": "owner-key"}}
    client = TestClient(create_app(app_cfg))
    operator = {"Authorization": "Bearer owner-key"}

    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    ana = {"Authorization": f"Bearer {token}"}

    posted = client.post("/v1/city/chat", headers=ana,
                         json={"city": "Lisbon", "text": "something threatening"}).json()
    client.post("/v1/city/chat/report", headers=ana,
                json={"message_id": posted["message_id"], "reason": "abuse"})

    reports = client.get("/v1/city/chat/reports", headers=operator).json()["reports"]
    assert len(reports) == 1
    assert reports[0]["quoted_text"] == "something threatening"
    assert reports[0]["reason"] == "abuse"

    resolved = client.post("/v1/city/chat/reports/resolve", headers=operator, json={
        "report_id": reports[0]["report_id"], "action": "actioned",
        "remove_message": True})
    assert resolved.status_code == 200
    assert client.get("/v1/city/chat?city=Lisbon",
                      headers=ana).json()["messages"] == []
    assert client.get("/v1/city/chat/reports", headers=operator).json()["reports"] == []


# ---- bounds --------------------------------------------------------------------

def test_a_room_cannot_be_flooded_by_one_account(room):
    """The gateway limits by IP; this limits by account. They stop different things — one
    script, versus one person with a phone and a grudge."""
    client, people = room
    for i in range(chat.MAX_PER_WINDOW):
        assert _say(client, people["mallory"], f"spam {i}").status_code == 200
    assert _say(client, people["mallory"], "spam again").status_code == 400
    # ...and it is per account, so it must not silence the room.
    assert _say(client, people["ana"], "still talking").status_code == 200


@pytest.mark.parametrize("bad", ["", "   ", "\n\t "])
def test_an_empty_message_is_refused(room, bad):
    client, people = room
    assert _say(client, people["ana"], bad).status_code == 400


def test_a_message_is_length_capped(room):
    client, people = room
    assert _say(client, people["ana"], "x" * (chat.MAX_TEXT + 1)).status_code == 400
    assert _say(client, people["ana"], "x" * chat.MAX_TEXT).status_code == 200


def test_messages_expire(graph, monkeypatch):
    """A room that remembers forever is a record of where somebody was on a given night."""
    chat.post(graph, "Lisbon", "tonight only", author_id="acct-1", author_handle="ana")
    assert len(chat.messages(graph, "Lisbon")["messages"]) == 1

    later = (datetime.datetime.now(datetime.timezone.utc)
             + datetime.timedelta(days=chat.RETENTION_DAYS + 1))
    monkeypatch.setattr(chat, "_now", lambda: later)
    assert chat.messages(graph, "Lisbon")["messages"] == []
    assert chat.active_cities(graph) == []


def test_a_nameless_city_is_refused(graph):
    for bad in ("", "   ", "!!!", "---"):
        with pytest.raises(chat.ChatError):
            chat.post(graph, bad, "hi", author_id="a")


def test_the_room_is_bounded(room):
    """A client asking for a million messages gets a page, not the database."""
    client, people = room
    body = client.get(f"/v1/city/chat?city=Lisbon&limit=99999",
                      headers=people["ana"]["h"]).json()
    assert body["retention_days"] == chat.RETENTION_DAYS
    assert len(body["messages"]) <= chat.MAX_LIMIT
