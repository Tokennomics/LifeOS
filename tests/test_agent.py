"""The agent: goals -> plans, memory you control, check-ins, and approval before action.

What is pinned here is the honesty of the loop rather than its wording: starter steps say
they are starters, nothing runs without an approve, a drafted message is never reported as
sent, the model sees exactly the listed context, and an open question without a key is
declined rather than answered with prose.
"""

import datetime
import json

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.agent import core as agent


class FakeClaude:
    available = True

    def __init__(self, answer=None, fail=False):
        self.answer = answer or {}
        self.fail = fail
        self.calls = []

    def complete_json(self, system, user, *, schema, model=None, max_tokens=16000):
        self.calls.append({"system": system, "user": json.loads(user)})
        if self.fail:
            raise RuntimeError("boom")
        return self.answer


# ---- plans ---------------------------------------------------------------------

def test_without_a_key_a_goal_gets_starter_steps_that_say_so(graph):
    g = agent.create_goal(graph, "Run a half marathon")
    assert g["planned_by"] == "starter"
    assert g["assisted"] is False
    assert [s["title"] for s in g["steps"]] == list(agent.STARTER_STEPS)
    assert "starter" in g["note"].lower() and "ANTHROPIC_API_KEY" in g["note"]


def test_your_own_steps_win_over_any_model(graph):
    fake = FakeClaude({"steps": ["model step"], "note": ""})
    g = agent.create_goal(graph, "Learn Portuguese", steps=["Buy a course", "Book a tutor"],
                          claude=fake)
    assert [s["title"] for s in g["steps"]] == ["Buy a course", "Book a tutor"]
    assert g["planned_by"] == "you"
    assert fake.calls == []


def test_with_a_key_the_model_drafts_the_plan_from_goal_and_memory(graph):
    agent.remember(graph, "I only train in the evenings")
    fake = FakeClaude({"steps": ["Find a 12-week plan", "Run 3 km tonight"], "note": "n"})
    g = agent.create_goal(graph, "Run a half marathon", deadline="2027-03-01", claude=fake)
    assert g["planned_by"] == "model" and g["assisted"] is True
    assert [s["title"] for s in g["steps"]] == ["Find a 12-week plan", "Run 3 km tonight"]
    sent = fake.calls[0]["user"]
    assert sent == {"goal": "Run a half marathon", "deadline": "2027-03-01",
                    "remembered": ["I only train in the evenings"]}


def test_a_model_failure_falls_back_to_starters_rather_than_500ing(graph):
    g = agent.create_goal(graph, "Move to Lisbon", claude=FakeClaude(fail=True))
    assert g["planned_by"] == "starter" and g["assisted"] is False


def test_a_bad_deadline_is_refused(graph):
    with pytest.raises(ValueError):
        agent.create_goal(graph, "x", deadline="next week")


def test_goals_are_the_planners_goals(graph):
    """Agent goals are ordinary plan-level goals, so the weekly planner sees them."""
    from modules.horizon import planner
    g = agent.create_goal(graph, "Ship the app")
    assert g["id"] in [x["id"] for x in planner.list_goals(graph)]


def test_finishing_every_step_finishes_the_goal(graph):
    g = agent.create_goal(graph, "Tiny goal", steps=["one", "two"])
    agent.complete_step(graph, g["steps"][0]["id"])
    mid = agent.goal(graph, g["id"])
    assert (mid["done"], mid["of"], mid["next_step"]["title"]) == (1, 2, "two")
    done = agent.complete_step(graph, g["steps"][1]["id"])
    assert done["status"] == "done"
    assert g["id"] not in [x["id"] for x in agent.goals(graph)]
    assert g["id"] in [x["id"] for x in agent.goals(graph, include_done=True)]


# ---- memory --------------------------------------------------------------------

def test_memory_is_exactly_what_you_said_and_can_be_deleted(graph):
    r = agent.remember(graph, "  I am vegetarian  ")
    assert r["stored"] and r["text"] == "I am vegetarian"
    assert agent.remember(graph, "i am VEGETARIAN")["stored"] is False
    assert [f["text"] for f in agent.facts(graph)] == ["I am vegetarian"]
    agent.forget(graph, r["id"])
    assert agent.facts(graph) == []


# ---- check-in ------------------------------------------------------------------

def test_a_quiet_checkin_is_quiet(graph):
    c = agent.checkin(graph)
    assert c["quiet"] is True and c["needs_you"] == [] and c["next_steps"] == []


def test_checkin_counts_deadlines_and_approvals_from_rows(graph):
    soon = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
    past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    agent.create_goal(graph, "Soon", deadline=soon, steps=["a", "b"])
    agent.create_goal(graph, "Late", deadline=past, steps=["a"])
    agent.propose(graph, "remember", {"text": "x"})
    kinds = sorted(i["kind"] for i in agent.checkin(graph)["needs_you"])
    assert kinds == ["approval", "deadline", "overdue"]


def test_a_goal_untouched_for_a_week_is_called_stalled(graph):
    g = agent.create_goal(graph, "Learn chess", steps=["a", "b"])
    assert "stalled" not in [i["kind"] for i in agent.checkin(graph)["needs_you"]]
    old = (agent._now() - datetime.timedelta(days=agent.STALL_DAYS + 3)).isoformat()
    graph._execute("UPDATE entities SET created_at = ? WHERE id = ?", (old, g["id"]))
    graph.conn.commit()
    stalled = [i for i in agent.checkin(graph)["needs_you"] if i["kind"] == "stalled"]
    assert [i["goal_id"] for i in stalled] == [g["id"]]
    # Ticking a step is progress, so the same old goal stops being stalled.
    agent.complete_step(graph, g["steps"][0]["id"])
    assert "stalled" not in [i["kind"] for i in agent.checkin(graph)["needs_you"]]


# ---- propose, authorise, execute -----------------------------------------------

def test_a_proposal_does_nothing_until_approved(graph):
    p = agent.propose(graph, "add_task", {"title": "Call the landlord"})
    session = graph.session("t", {"tasks:read"})
    assert not session.find_entities("task", {"title": "Call the landlord"})
    out = agent.approve(graph, p["id"])
    assert out["result"]["done"] is True
    assert session.find_entities("task", {"title": "Call the landlord"})
    with pytest.raises(ValueError):
        agent.approve(graph, p["id"])


def test_a_rejected_proposal_never_runs(graph):
    p = agent.propose(graph, "remember", {"text": "secret"})
    agent.reject(graph, p["id"])
    with pytest.raises(ValueError):
        agent.approve(graph, p["id"])
    assert agent.facts(graph) == []


def test_only_whitelisted_actions_can_be_proposed(graph):
    for action in ("send_email", "buy", "book_flight", ""):
        with pytest.raises(ValueError):
            agent.propose(graph, action, {})


def test_a_drafted_message_is_never_reported_as_sent(graph):
    p = agent.propose(graph, "draft_message",
                      {"channel": "email", "to": "sam@example.org", "subject": "Hi",
                       "body": "Dinner Friday?"})
    result = agent.approve(graph, p["id"])["result"]
    assert result["sent"] is False
    assert result["open"].startswith("mailto:sam@example.org?")
    sms = agent.approve(graph, agent.propose(
        graph, "draft_message", {"channel": "sms", "to": "+351 900", "body": "hey"})["id"])
    assert sms["result"]["open"].startswith("sms:") and sms["result"]["sent"] is False


# ---- conversation --------------------------------------------------------------

def test_plain_commands_work_without_a_key(graph):
    assert agent.ask(graph, "remember I hate mornings")["intent"] == "remember"
    assert "I hate mornings" in agent.ask(graph, "what do you know about me?")["reply"]
    g = agent.ask(graph, "I want to learn to surf by 2027-06-01")
    assert g["intent"] == "goal" and g["goal"]["deadline"] == "2027-06-01"
    assert g["goal"]["title"] == "learn to surf"
    assert agent.ask(graph, "what's next?")["intent"] == "checkin"
    assert agent.ask(graph, "forget mornings")["forgotten"] == ["I hate mornings"]


def test_an_open_question_without_a_key_is_declined_not_invented(graph):
    r = agent.ask(graph, "Where should I eat tonight?")
    assert r["available"] is False and r["needs"] == ["ANTHROPIC_API_KEY"]
    assert r["assisted"] is False
    assert "proposals" not in r


def test_the_model_only_proposes_and_sees_only_the_listed_context(graph):
    agent.remember(graph, "I live in Porto")
    fake = FakeClaude({"reply": "Try this.", "proposals": [
        {"action": "add_task", "summary": "Add a run", "args_json": '{"title": "Run 5k"}'},
        {"action": "add_task", "summary": "broken", "args_json": "{not json"},
    ]})
    r = agent.ask(graph, "How do I get fitter?", claude=fake)
    assert r["assisted"] is True
    assert [p["summary"] for p in r["proposals"]] == ["Add a run"]
    assert "1 suggested action" in r["note"]
    assert fake.calls[0]["user"]["facts"] == agent.context(graph) | {
        "pending_approvals": []}
    session = graph.session("t", {"tasks:read"})
    assert not session.find_entities("task", {"title": "Run 5k"})


# ---- over HTTP -----------------------------------------------------------------

def test_the_routes_round_trip(cfg):
    c = TestClient(create_app(cfg))
    g = c.post("/v1/agent/goals", json={"title": "Write a book"}).json()
    assert g["planned_by"] == "starter"
    step = g["steps"][0]["id"]
    assert c.post(f"/v1/agent/steps/{step}/done").json()["done"] == 1
    assert c.post(f"/v1/agent/goals/{g['id']}/steps", json={"title": "Outline"}).json()["of"] == 4
    fact = c.post("/v1/agent/memory", json={"text": "I write at night"}).json()
    assert c.get("/v1/agent/memory").json()["memory"][0]["text"] == "I write at night"
    assert c.delete(f"/v1/agent/memory/{fact['id']}").json()["forgotten"] is True
    p = c.post("/v1/agent/proposals", json={"action": "set_focus",
                                            "args": {"goal_id": g["id"]}}).json()
    assert [x["id"] for x in c.get("/v1/agent/proposals").json()["proposals"]] == [p["id"]]
    assert c.post(f"/v1/agent/proposals/{p['id']}/approve").json()["status"] == "approved"
    assert c.get("/v1/agent/goals").json()["goals"][0]["focus"] is True
    assert c.post("/v1/agent/proposals", json={"action": "buy", "args": {}}).status_code == 400
    assert c.post("/v1/agent/ask", json={"message": "what's next?"}).status_code == 200
    assert c.get("/v1/agent/checkin").status_code == 200
    assert c.get("/v1/agent/context").json()["goals"][0]["title"] == "Write a book"
