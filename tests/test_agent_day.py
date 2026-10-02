"""The agent plans a day out of rows, and books nothing.

Pinned: a plan only contains listed events, meetups and seeded places for that day and
city; anything already in your calendar is not double-booked; a model may choose and order
but an id it invents is thrown away; every stop is a pending proposal, and approving one
puts a real event in your own calendar (so the calendar feed carries it).
"""

import datetime
import json

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.agent import core, day
from substrate import SYSTEM_OWNER
from substrate.graph import Graph

SAT = datetime.date(2026, 10, 10)          # a Saturday


@pytest.fixture(autouse=True)
def _no_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


def _public_event(graph, title, start, end="", city="Lisbon", url=""):
    Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(
        "t", {"events:write"}).create_entity("event", {
            "type": "social", "title": title, "start": start, "end": end, "city": city,
            "visibility": "public", "origin": "feed", "venue": "Venue", "url": url},
        source="test", owner_id=SYSTEM_OWNER)


def _place(graph, name, category, city="lisbon"):
    Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(
        "t", {"content:write"}).create_entity("content", {
            "type": "city_place", "city": city, "name": name, "category": category},
        source="test")


@pytest.fixture
def lisbon(graph, monkeypatch):
    monkeypatch.setattr(day, "resolve_day", lambda w, today=None: SAT)
    _public_event(graph, "Fado night", "2026-10-10T21:00:00+00:00", "2026-10-10T23:00:00+00:00",
                  url="https://tickets.example/fado")
    _public_event(graph, "Morning market tour", "2026-10-10T10:00:00+00:00")
    _public_event(graph, "Sunday jazz", "2026-10-11T18:00:00+00:00")
    _public_event(graph, "Porto gig", "2026-10-10T20:00:00+00:00", city="Porto")
    _place(graph, "Café Real", "coffee")
    _place(graph, "Jardim da Estrela", "park")
    return graph


# ---- the day -------------------------------------------------------------------

@pytest.mark.parametrize("word,expect", [
    ("today", "2026-10-07"), ("tonight", "2026-10-07"), ("tomorrow", "2026-10-08"),
    ("saturday", "2026-10-10"), ("wednesday", "2026-10-07"), ("2026-12-24", "2026-12-24")])
def test_the_day_words(word, expect):
    assert day.resolve_day(word, datetime.date(2026, 10, 7)).isoformat() == expect


def test_an_unknown_day_is_refused():
    with pytest.raises(ValueError):
        day.resolve_day("someday")


@pytest.mark.parametrize("text,expect", [
    ("plan my Saturday in Lisbon", ("Saturday", "Lisbon")),
    ("Plan tomorrow", ("tomorrow", "")),
    ("plan today in New York?", ("today", "New York")),
    ("plan to run a marathon", None),
])
def test_the_request_is_recognised(text, expect):
    assert day.match(text) == expect


# ---- the plan --------------------------------------------------------------------

def test_without_a_key_the_plan_is_that_days_listings_then_places(lisbon):
    out = day.plan(lisbon, "saturday", "Lisbon")
    titles = [s["title"] for s in out["stops"]]
    assert titles[:2] == ["Morning market tour", "Fado night"]
    assert "Sunday jazz" not in titles and "Porto gig" not in titles
    assert set(titles[2:]) <= {"Café Real", "Jardim da Estrela"}
    assert out["assisted"] is False


def test_every_stop_is_a_pending_proposal_and_nothing_is_booked(lisbon):
    out = day.plan(lisbon, "saturday", "Lisbon")
    assert len(out["proposals"]) == len(out["stops"])
    assert {p["action"] for p in out["proposals"]} == {"add_plan"}
    mine = lisbon.session("t", {"events:read"}).find_entities("event", {"origin": "agent_plan"})
    assert mine == []


def test_approving_a_stop_puts_it_in_your_calendar_with_its_ticket_link(lisbon):
    out = day.plan(lisbon, "saturday", "Lisbon")
    fado = [p for p in out["proposals"] if "Fado" in p["summary"]][0]
    assert fado["summary"].startswith("21:00")
    result = core.approve(lisbon, fado["id"])["result"]
    assert result["done"] and result["url"] == "https://tickets.example/fado"
    mine = lisbon.session("t", {"events:read"}).find_entities("event", {"origin": "agent_plan"})
    assert [e["attrs"]["title"] for e in mine] == ["Fado night"]
    assert mine[0]["attrs"]["busy"] is True
    from modules.calendars import export
    assert "Fado night" in export.export_user_ics(lisbon)


def test_what_you_already_have_on_is_not_double_booked(lisbon):
    lisbon.session("t", {"events:write"}).create_entity("event", {
        "title": "Dinner with Sam", "start": "2026-10-10T20:30:00+00:00",
        "end": "2026-10-10T22:00:00+00:00", "busy": True}, source="test")
    out = day.plan(lisbon, "saturday", "Lisbon")
    assert "Fado night" not in [s["title"] for s in out["stops"]]
    assert out["clashed"][0]["clashes_with"] == "Dinner with Sam"


def test_an_empty_day_says_so(graph, monkeypatch):
    monkeypatch.setattr(day, "resolve_day", lambda w, today=None: SAT)
    out = day.plan(graph, "saturday", "Lisbon")
    assert out["empty"] is True and out["proposals"] == [] and "Lisbon" in out["suggestion"]


def test_no_city_asks_for_one(graph):
    out = day.plan(graph, "today")
    assert out["city"] == "" and "Which city" in out["suggestion"]


class Fake:
    available = True

    def __init__(self, answer):
        self.answer, self.sent = answer, None

    def complete_json(self, system, user, *, schema, max_tokens=1200, model=None):
        self.sent = json.loads(user)
        return self.answer


def test_a_model_chooses_from_candidates_and_cannot_add_any(lisbon):
    pool = day.candidates(lisbon, SAT, "Lisbon")
    fado = [s for s in pool["timed"] if s["title"] == "Fado night"][0]["id"]
    fake = Fake({"stops": [{"id": "invented-rooftop-bar", "why": "views"},
                           {"id": fado, "why": "the night's main thing"}], "note": "n"})
    out = day.plan(lisbon, "saturday", "Lisbon", claude=fake)
    assert out["assisted"] is True
    assert [(s["title"], s["why"]) for s in out["stops"]] == [("Fado night", "the night's main thing")]
    assert {c["id"] for c in fake.sent["candidates"]} >= {fado}


def test_a_model_failure_falls_back_to_the_assembled_plan(lisbon):
    class Broken(Fake):
        def complete_json(self, *a, **k):
            raise RuntimeError("down")
    out = day.plan(lisbon, "saturday", "Lisbon", claude=Broken({}))
    assert out["assisted"] is False and out["stops"]


# ---- through the agent -------------------------------------------------------------

def test_the_agent_understands_plan_my_saturday(lisbon):
    r = core.ask(lisbon, "plan my Saturday in Lisbon")
    assert r["intent"] == "plan" and "Fado night" in r["reply"]
    assert len(r["proposals"]) >= 2


def test_plan_a_day_does_not_become_a_goal(lisbon):
    core.ask(lisbon, "plan tomorrow in Lisbon")
    assert core.goals(lisbon) == []


def test_the_route(cfg):
    client = TestClient(create_app(cfg))
    r = client.post("/v1/agent/plan-day", json={"when": "saturday", "city": "Lisbon"})
    assert r.status_code == 200 and r.json()["empty"] is True
    assert client.post("/v1/agent/plan-day", json={"when": "someday", "city": "x"}).status_code == 400


def test_a_place_has_no_time_so_it_becomes_a_task_not_a_midnight_event(lisbon):
    out = day.plan(lisbon, "saturday", "Lisbon")
    cafe = [p for p in out["proposals"] if "Café Real" in p["summary"]][0]
    assert cafe["summary"].startswith("any time")
    result = core.approve(lisbon, cafe["id"])["result"]
    assert "task_id" in result and "event_id" not in result
    tasks = lisbon.session("t", {"tasks:read"}).find_entities("task", {"origin": "agent_plan"})
    assert tasks[0]["attrs"]["title"] == "Café Real (any time 2026-10-10)"
    assert tasks[0]["attrs"]["week"] == "2026-W41"
