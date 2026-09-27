"""The voice copilot answers from rows, or says it has none.

The no-key path used to answer "Hey Robert! … weather is 29.6°C. You have 3 friends
nearby …" for any question in any city, and named Blitz Club, Julius Brantner and
"Lukas and Sophie" for the topics it recognised. These pin the replacement: every name in
a reply is a row the caller can see, and an empty city is empty.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.ai import assist
from substrate import SYSTEM_OWNER
from substrate.graph import Graph


def _soon(hours=3):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=hours)).isoformat()


def _place(graph, city, name, category):
    Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(
        "t", {"content:write"}).create_entity(
        "content", {"type": "city_place", "city": city, "name": name, "category": category},
        source="test")


class Fake:
    available = True

    def __init__(self):
        self.user = ""

    def complete(self, system, user, max_tokens=700):
        self.user = user
        return "Worded by the model."


@pytest.mark.parametrize("query", ["what's on tonight?", "where can I get coffee?",
                                   "who from my squad is around?", "tell me something"])
def test_an_empty_city_names_nothing(graph, query):
    out = assist.copilot(graph, query, "munich")
    assert out["empty"] is True and out["sources"] == []
    assert out["suggestion"]
    for invented in ("blitz", "brantner", "robert", "29.6", "lukas", "sophie", "3 friends"):
        assert invented not in out["voice_reply_text"].lower()


def test_food_answers_with_seeded_places_only(graph):
    _place(graph, "lisbon", "Copenhagen Coffee Lab", "coffee")
    _place(graph, "lisbon", "Jardim da Estrela", "park")
    out = assist.copilot(graph, "where can I get coffee", "Lisbon")
    assert out["topic"] == "FOOD"
    assert "Copenhagen Coffee Lab" in out["voice_reply_text"]
    assert "Jardim" not in out["voice_reply_text"]
    assert [s["what"] for s in out["sources"]] == ["Copenhagen Coffee Lab"]


def test_tonight_answers_with_real_events(graph, monkeypatch):
    monkeypatch.setattr(assist, "grounding", lambda g, **kw: {
        "city": "lisbon", "meetups": [], "your_plans": [], "your_signals": [], "empty": False,
        "events": [{"id": "e1", "title": "Fado night", "start": _soon(), "venue": "Tasca"}]})
    out = assist.copilot(graph, "what's on tonight", "lisbon")
    assert out["topic"] == "TONIGHT" and "Fado night" in out["voice_reply_text"]
    assert out["sources"][0]["ref"] == "e1"


def test_people_never_claims_to_know_locations(graph):
    out = assist.copilot(graph, "who from my squad is nearby", "lisbon")
    assert out["topic"] == "PEOPLE"
    assert "doesn't track locations" in out["voice_reply_text"]


def test_no_city_asks_rather_than_guessing(graph):
    out = assist.copilot(graph, "coffee?")
    assert out["city"] == "" and "Which city" in out["voice_reply_text"]


def test_the_model_only_rewords_the_rows(graph):
    _place(graph, "lisbon", "Fábrica Coffee", "coffee")
    fake = Fake()
    out = assist.copilot(graph, "coffee", "lisbon", claude=fake)
    assert out["assisted"] is True and out["voice_reply_text"] == "Worded by the model."
    assert "Fábrica Coffee" in fake.user


def test_the_model_is_not_asked_when_there_is_nothing(graph):
    fake = Fake()
    out = assist.copilot(graph, "coffee", "lisbon", claude=fake)
    assert fake.user == "" and out["assisted"] is False


def test_an_empty_question_is_refused(graph):
    with pytest.raises(ValueError):
        assist.copilot(graph, "  ", "lisbon")


def test_the_spoken_markup_is_escaped(cfg, graph):
    """Place names are typed by people, and the reply is spoken from SSML. A name with
    markup in it must stay text."""
    _place(graph, "lisbon", "Tom & <break time='9s'/> Jerry", "coffee")
    client = TestClient(create_app(cfg))
    res = client.post("/v1/voice/copilot-chat", json={"query": "coffee", "city": "Lisbon"})
    assert res.status_code == 200
    ssml = res.json()["tts_ssml"]
    assert "Tom &amp; &lt;break" in ssml and "<break" not in ssml
    assert client.post("/v1/voice/copilot-chat", json={"query": ""}).status_code == 400
