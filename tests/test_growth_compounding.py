import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.triage import brief
from modules.vault import auto_linker
from modules.horizon import micro_planner
from modules.crews import invites, crews
from substrate.graph import Graph


def test_daily_brief_enriched(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Pre-seed sleep record
    session.create_entity("admin_item", {
        "type": "sleep_record",
        "date": "2026-08-04",
        "hours_slept": 7.5,
        "sleep_quality": 8,
        "wake_time": "07:30"
    }, source="test")
    
    # Pre-seed financial goal
    session.create_entity("goal", {
        "type": "financial_goal",
        "title": "Lisbon Runway",
        "target_amount": 10000.0,
        "current_amount": 3500.0,
        "currency": "EUR"
    }, source="test")
    
    # Generate brief with coordinates
    res = brief.generate_triage_brief(graph, lat=38.7223, lon=-9.1393)
    
    # Verify sleep integration
    assert res["sleep_summary"]["last_night"] is not None
    assert res["sleep_summary"]["last_night"]["hours"] == 7.5
    assert res["sleep_summary"]["last_night"]["quality"] == 8
    
    # Verify finance integration
    assert res["finance_summary"]["goals_count"] == 1
    assert res["finance_summary"]["total_target"] == 10000.0
    assert res["finance_summary"]["total_current"] == 3500.0
    
    # Verify habit recommendation integration
    assert res["recommended_habit"] is not None


def test_capture_to_goal_linker(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Pre-seed a goal
    goal_id = session.create_entity("goal", {
        "title": "Learn climbing and bouldering in Lisbon"
    }, source="test")
    
    # Pre-seed a capture with matching keyword
    cap_id = session.create_entity("content", {
        "type": "capture",
        "text": "Need to book climbing class tomorrow morning"
    }, source="test")
    
    # Run the auto-linker
    proposals = auto_linker.auto_link_captures_to_goals(graph)
    assert len(proposals) >= 1
    
    prop = [p for p in proposals if p["capture_id"] == cap_id][0]
    assert prop["goal_id"] == goal_id
    
    # Accept proposal
    accept_res = auto_linker.accept_capture_link(graph, cap_id, goal_id)
    assert accept_res["created"] is True
    
    # Verify edge exists
    edges = session.neighbors(cap_id, rel="feeds")
    assert any(nb["id"] == goal_id for nb in edges)


def test_procrastination_micro_planner(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Pre-seed stuck task (carries > 2)
    task_id = session.create_entity("task", {
        "title": "Complete Lisbon travel presentation deck",
        "status": "open",
        "carries": 3,
        "week": "2026-W32"
    }, source="test")
    
    # Get micro-break suggestions
    proposals = micro_planner.suggest_micro_breaks(graph)
    assert len(proposals) >= 1
    
    prop = [p for p in proposals if p["task_id"] == task_id][0]
    assert len(prop["steps"]) == 3
    
    # Execute the micro-break plan
    exec_res = micro_planner.execute_micro_break_plan(graph, task_id, prop["steps"])
    assert exec_res["status"] == "split_successful"
    assert len(exec_res["child_tasks"]) == 3
    
    # Verify parent task is marked as split (not open anymore)
    parent_updated = session.get_entity(task_id)
    assert parent_updated["attrs"]["status"] == "split"
    
    # Verify child tasks are open and linked
    for cid in exec_res["child_tasks"]:
        child = session.get_entity(cid)
        assert child["attrs"]["status"] == "open"
        edges = session.neighbors(task_id, rel="feeds")
        assert any(nb["id"] == cid for nb in edges)


def test_invite_landing_page(cfg, graph: Graph):
    app = create_app(cfg)
    client = TestClient(app)
    
    # Create a crew (no admin needed, mine=True)
    crew_res = crews.create(graph, "Lisbon Coders", city="Lisbon")
    crew_id = crew_res["id"]
    
    # Create an invite link for this crew
    link_info = invites.create(graph, crew_id)
    token = link_info["token"]
    
    # Fetch landing page
    resp = client.get(f"/invite/{token}")
    assert resp.status_code == 200
    assert "Lisbon Coders" in resp.text
    assert "Join Crew" in resp.text
    
    # Fetch expired/invalid token
    resp_exp = client.get("/invite/invalid_token")
    assert resp_exp.status_code == 200
    assert "Invite Link Expired" in resp_exp.text

