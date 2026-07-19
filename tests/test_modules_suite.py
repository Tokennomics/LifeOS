import pytest

from billing import stripe
from modules.calibre import decisions as calibre
from modules.hearth import spaces as hearth
from modules.horizon import planner
from modules.ledger import ledger
from modules.reconnect import decay
from modules.vitals import energy


def test_vitals_defaults_set_and_planner_consumes_peak(graph):
    assert energy.windows(graph)[0]["phase"] == "peak"
    seen = []
    graph.bus.subscribe("energy.updated", lambda t, p: seen.append(p))
    energy.set_windows(graph, [{"phase": "peak", "start": "06:30", "end": "09:00"},
                               {"phase": "trough", "start": "13:00", "end": "15:00"}])
    assert seen and energy.phase_start(graph, "peak", "17:00") == "06:30"
    with pytest.raises(ValueError):
        energy.set_windows(graph, [{"phase": "zoomies", "start": "01:00", "end": "02:00"}])

    # offline planner schedules goal-fallback tasks into the peak window
    graph.session("horizon", {"goals:write"}).create_entity(
        "goal", {"level": "goal", "title": "Deep work"}, source="seed")
    planner.plan_week(graph)
    tasks = planner.week_tasks(graph)
    assert "06:30" in tasks[0]["attrs"]["if_then"]


def test_ledger_log_and_summary(graph):
    ledger.log_spend(graph, 42.50, "Food", "groceries")
    ledger.log_spend(graph, 12, "food")
    ledger.log_spend(graph, 99.99, "gear")
    with pytest.raises(ValueError):
        ledger.log_spend(graph, -5, "oops")
    summary = ledger.summary(graph)
    assert summary["total"] == 154.49
    assert summary["by_category"]["food"] == 54.5
    assert summary["count"] == 3


def test_calibre_brier_scoring(graph):
    with pytest.raises(ValueError):
        calibre.log(graph, "bad", "x", 1.5, "y")
    decision_id = calibre.log(graph, "Promote model", "ship it", 0.8, "stays profitable 30d")
    assert calibre.open_decisions(graph)[0]["title"] == "Promote model"
    result = calibre.resolve(graph, decision_id, happened=False)
    assert result["brier"] == 0.64  # confident and wrong hurts
    assert calibre.open_decisions(graph) == []
    calibration = calibre.calibration(graph)
    assert calibration == {"n": 1, "avg_brier": 0.64}


def test_hearth_spaces_and_grants(graph):
    sam = decay.add_person(graph, "Sam")
    space = hearth.create_space(graph, "Home", [sam])
    assert space["members"] == 1
    with pytest.raises(ValueError):
        hearth.create_space(graph, "Home")
    listed = hearth.spaces(graph)
    assert listed[0]["name"] == "Home"
    assert listed[0]["members"] == ["Sam"]
    hearth.add_member(graph, space["space_id"], decay.add_person(graph, "Alex"))
    assert sorted(hearth.spaces(graph)[0]["members"]) == ["Alex", "Sam"]


def test_billing_off_by_default():
    cfg = {"billing": {"stripe_key": ""}}
    assert stripe.billing_enabled(cfg) is False
    assert stripe.entitled(cfg, "steward_automations") is True
    assert stripe.entitled({"billing": {"stripe_key": "sk_x"}}, "steward_automations") is False
    assert stripe.entitled({"billing": {"stripe_key": "sk_x"}}, "export") is True
