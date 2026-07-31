import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from gateway.main import create_app
from modules.horizon import milestone_nudges
from substrate.graph import Graph


def test_milestone_nudges_scan(graph: Graph):
    session = graph.session("test", {"*"})
    now = datetime.now(timezone.utc)
    
    # Goal with overdue milestone
    overdue_due = (now - timedelta(days=2)).isoformat()
    session.create_entity(
        "goal",
        {
            "title": "Overdue Goal",
            "level": "goal",
            "milestones": [
                {"title": "Step 1", "due_date": overdue_due, "status": "pending"}
            ]
        },
        source="test"
    )

    # Goal with due soon milestone
    soon_due = (now + timedelta(days=2)).isoformat()
    session.create_entity(
        "goal",
        {
            "title": "Soon Goal",
            "level": "goal",
            "milestones": [
                {"title": "Step 2", "due_date": soon_due, "status": "pending"}
            ]
        },
        source="test"
    )

    nudges = milestone_nudges.scan_milestone_nudges(graph)
    assert len(nudges) >= 2
    assert any(n["status"] == "overdue" for n in nudges)
    assert any(n["status"] == "due_soon" for n in nudges)


def test_gateway_nudges_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)
    resp = client.post("/v1/goals/nudges/scan")
    assert resp.status_code == 200
