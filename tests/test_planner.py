import pytest

from modules.horizon import gate, planner


@pytest.fixture(autouse=True)
def _gate_passed(monkeypatch):
    # These tests isolate planner mechanics; lift the gate floor (covered in
    # test_anti_hindrance) so a fresh graph doesn't inject the gate-ritual slot.
    monkeypatch.setattr(gate, "gate_status", lambda g: {"cleared": True})


class FakeClaude:
    available = True

    def __init__(self, data):
        self.data = data

    def complete_json(self, system, user, *, schema, model=None, max_tokens=16000):
        return self.data


def _seed_goal(graph, title="Ship v0.1"):
    s = graph.session("horizon", planner.SCOPES | {"goals:write"})
    return s.create_entity("goal", {"level": "goal", "title": title}, source="seed")


def _seed_task(graph, title="Write planner"):
    s = graph.session("horizon", planner.SCOPES)
    return s.create_entity("task", {"title": title, "status": "open", "if_then": ""}, source="seed")


def test_offline_plan_assigns_week_to_open_tasks(graph):
    tid = _seed_task(graph)
    result = planner.plan_week(graph)
    assert result["method"] == "offline"
    assert result["tasks"] == 1
    s = graph.session("horizon", planner.SCOPES)
    assert s.get_entity(tid)["attrs"]["week"] == result["week"]


def test_offline_plan_falls_back_to_goals(graph):
    _seed_goal(graph, "Train 3x/week")
    result = planner.plan_week(graph)
    tasks = planner.week_tasks(graph, result["week"])
    assert len(tasks) == 1
    assert tasks[0]["attrs"]["title"].startswith("Advance:")
    assert tasks[0]["attrs"]["if_then"].startswith("If it's")


def test_plan_idempotent_when_week_already_planned(graph):
    for i in range(3):
        _seed_task(graph, f"t{i}")
    first = planner.plan_week(graph)
    again = planner.plan_week(graph)
    assert again["method"] == "already-planned"
    assert len(planner.week_tasks(graph, first["week"])) == 3


def test_claude_plan_reuses_and_creates(graph):
    gid = _seed_goal(graph, "Run a 10k")
    tid = _seed_task(graph, "Buy running shoes")
    fake = FakeClaude({"tasks": [
        {"title": "Buy running shoes", "if_then": "If it's Sat 10:00, then I go to the store",
         "existing_task_id": tid, "goal_title": ""},
        {"title": "Run 3k", "if_then": "If it's Tue 18:00, then I run 3k",
         "existing_task_id": "", "goal_title": "Run a 10k"},
    ]})
    result = planner.plan_week(graph, claude=fake)
    assert result["tasks"] == 2
    s = graph.session("horizon", planner.SCOPES)
    assert s.get_entity(tid)["attrs"]["if_then"].startswith("If it's Sat")
    new_task = [t for t in planner.week_tasks(graph) if t["attrs"]["title"] == "Run 3k"][0]
    assert s.neighbors(new_task["id"], rel="feeds", direction="out")[0]["id"] == gid


def test_format_and_log(graph):
    _seed_task(graph, "Do the thing")
    planner.plan_week(graph)
    text = planner.format_week(graph)
    assert "1. [ ] Do the thing" in text
    title = planner.log_done(graph, 1)
    assert title == "Do the thing"
    assert "1. [x]" in planner.format_week(graph)
    with pytest.raises(ValueError):
        planner.log_done(graph, 9)
