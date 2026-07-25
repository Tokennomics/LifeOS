"""T3 anti-hindrance mechanics at the graph level (the wiring around core.py)."""

from modules.horizon import gate, planner, retro, vision_intake
from modules.voiceos import capture


def _goal(graph, title):
    s = graph.session("horizon", {"goals:write"})
    return s.create_entity("goal", {"level": "goal", "title": title}, source="seed")


def _open_task(graph, title, cycles=0):
    s = graph.session("horizon", {"tasks:write"})
    return s.create_entity("task", {"title": title, "status": "open", "if_then": "", "cycles": cycles}, source="seed")


def _pass_gate(monkeypatch):
    """Pretend the v0.1 gate is already passed, so the gate floor lifts and the
    mechanic under test is isolated. plan_week reads gate.gate_status at call time."""
    monkeypatch.setattr(gate, "gate_status", lambda g: {"cleared": True})


# ---- distraction sink -------------------------------------------------------

def test_project_idea_is_parked_not_planned(graph):
    result = capture.capture("idea: build an app for tracking my runs", graph)
    assert result["parked"] is True
    assert result["message"] == "Captured, not abandoned — current gate first."
    assert capture.format_summary(result) == result["message"]
    parked = capture.list_parked(graph)
    assert len(parked) == 1 and "tracking my runs" in parked[0]["text"]
    s = graph.session("voiceos", capture.SCOPES)
    assert s.find_entities("content", {"type": "capture"}) == []


def test_ordinary_capture_is_not_parked(graph):
    result = capture.capture("remember the milk", graph)
    assert result["parked"] is False
    assert capture.list_parked(graph) == []


# ---- boredom rule -----------------------------------------------------------

def test_stale_task_surfaces_as_smallest_piece_and_blocks_new_work(graph, monkeypatch):
    _pass_gate(monkeypatch)
    _goal(graph, "Ship it")
    _open_task(graph, "Write the planner", cycles=2)  # a third cycle makes it stale
    planner.plan_week(graph)
    tasks = planner.week_tasks(graph)
    assert len(tasks) == 1  # only the stuck task; no new goal work starts
    t = tasks[0]["attrs"]
    assert t["smallest_piece"] is True
    assert t["cycles"] == 3
    assert "smallest remaining piece" in t["if_then"]


def test_most_stuck_task_is_planned_first(graph, monkeypatch):
    _pass_gate(monkeypatch)
    _open_task(graph, "fresh task", cycles=0)
    _open_task(graph, "old task", cycles=2)
    planner.plan_week(graph)
    by_title = {t["attrs"]["title"]: t["attrs"] for t in planner.week_tasks(graph)}
    assert "Monday" in by_title["old task"]["if_then"]
    assert "Monday" not in by_title["fresh task"]["if_then"]


# ---- energy shaping ---------------------------------------------------------

def test_deep_work_scheduled_to_evening_never_morning(graph, monkeypatch):
    _pass_gate(monkeypatch)
    _goal(graph, "Deep work")
    planner.plan_week(graph)
    if_then = planner.week_tasks(graph)[0]["attrs"]["if_then"]
    assert "20:00" in if_then and "09:00" not in if_then


def test_admin_routed_to_daytime_trough(graph, monkeypatch):
    _pass_gate(monkeypatch)
    _open_task(graph, "Email the accountant")
    planner.plan_week(graph)
    if_then = planner.week_tasks(graph)[0]["attrs"]["if_then"]
    assert "14:00" in if_then and "admin" in if_then


def test_tired_baseline_hard_caps_the_week(graph, monkeypatch):
    _pass_gate(monkeypatch)
    for i in range(6):
        _open_task(graph, f"task {i}")
    planner.plan_week(graph, energy_baseline="tired")
    assert len(planner.week_tasks(graph)) == 3


def test_rested_baseline_lifts_the_cap(graph, monkeypatch):
    _pass_gate(monkeypatch)
    for i in range(6):
        _open_task(graph, f"task {i}")
    planner.plan_week(graph, energy_baseline="rested")
    assert len(planner.week_tasks(graph)) == 6


# ---- gate-first goal ordering (focus) ---------------------------------------

def test_vision_intake_marks_first_goal_focus(graph):
    vision_intake.intake("Freedom\n- First goal\n- Second goal", graph)
    s = graph.session("horizon", {"goals:read"})
    focus = {g["attrs"]["title"]: g["attrs"].get("focus", False)
             for g in s.find_entities("goal", {"level": "goal"})}
    assert focus["First goal"] is True
    assert focus["Second goal"] is False


def test_focused_goal_leads_the_plan_over_input_order(graph, monkeypatch):
    _pass_gate(monkeypatch)
    _goal(graph, "Alpha")
    _goal(graph, "Bravo")
    charlie = _goal(graph, "Charlie")  # third by input order
    planner.set_goal_focus(graph, charlie, True)
    planner.plan_week(graph)
    by_title = {t["attrs"]["title"]: t["attrs"] for t in planner.week_tasks(graph)}
    assert "Monday" in by_title["Advance: Charlie"]["if_then"]
    assert "Monday" not in by_title["Advance: Alpha"]["if_then"]


def test_set_goal_focus_toggles_and_lists(graph):
    gid = _goal(graph, "Keystone")
    assert planner.set_goal_focus(graph, gid, True)["focus"] is True
    assert {g["title"]: g["focus"] for g in planner.list_goals(graph)}["Keystone"] is True
    planner.set_goal_focus(graph, gid, False)
    assert {g["title"]: g["focus"] for g in planner.list_goals(graph)}["Keystone"] is False


def test_focus_cap_limits_privileged_goals(graph, monkeypatch):
    _pass_gate(monkeypatch)
    _goal(graph, "A")
    _goal(graph, "B")
    for title in ("C", "D", "E"):
        planner.set_goal_focus(graph, _goal(graph, title), True)  # three stars
    planner.plan_week(graph)
    titles = [t["attrs"]["title"] for t in planner.week_tasks(graph)]
    assert "Advance: C" in titles and "Advance: D" in titles  # first two stars lead
    assert "Advance: E" not in titles                         # third star capped out
    assert "Advance: A" in titles                             # unstarred A beats it


# ---- gate floor -------------------------------------------------------------

def test_gate_floor_reserves_a_slot_while_unpassed(graph):
    _goal(graph, "Trading")
    _goal(graph, "Health")
    planner.plan_week(graph)  # empty history => gate unpassed
    tasks = planner.week_tasks(graph)
    assert any(t["attrs"].get("gate") for t in tasks)  # a gate-advancing task is present
    assert len(tasks) == 3                             # gate + 2 goals (tired cap)


def test_gate_floor_lifts_when_gate_passed(graph, monkeypatch):
    _pass_gate(monkeypatch)
    _goal(graph, "Trading")
    _goal(graph, "Health")
    planner.plan_week(graph)
    tasks = planner.week_tasks(graph)
    assert not any(t["attrs"].get("gate") for t in tasks)
    assert len(tasks) == 2


def test_gate_floor_holds_even_with_a_stale_carryover(graph):
    _open_task(graph, "Write the planner", cycles=2)  # stale, would block new work
    planner.plan_week(graph)  # gate unpassed
    tasks = planner.week_tasks(graph)
    assert any(t["attrs"].get("gate") for t in tasks)


# ---- doubt rule (/gate) -----------------------------------------------------

def test_gate_counts_are_real_not_estimated(graph):
    g0 = gate.gate_status(graph)
    assert (g0["days_used"], g0["logs_recorded"], g0["retros_completed"]) == (0, 0, 0)
    assert g0["cleared"] is False
    assert "0/28" in g0["text"]

    _open_task(graph, "a")
    _open_task(graph, "b")
    planner.plan_week(graph)
    planner.log_done(graph, 1)
    planner.log_done(graph, 2)
    retro.run_retro(graph)

    g1 = gate.gate_status(graph)
    assert g1["logs_recorded"] == 2
    assert g1["retros_completed"] == 1
    assert g1["days_used"] >= 1

    # Re-running the same week's retro must not inflate the count (distinct weeks).
    retro.run_retro(graph)
    assert gate.gate_status(graph)["retros_completed"] == 1
