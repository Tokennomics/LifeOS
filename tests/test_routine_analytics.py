import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.routines import analytics
from substrate.graph import Graph


def test_routine_analytics_aggregation(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Log routine streak items
    session.create_entity(
        "admin_item",
        {
            "type": "routine_streak",
            "name": "Exercise Daily",
            "streak": 5,
            "completed_today": True
        },
        source="test"
    )
    session.create_entity(
        "admin_item",
        {
            "type": "routine_streak",
            "name": "Read Daily",
            "streak": 3,
            "completed_today": False
        },
        source="test"
    )

    res = analytics.get_routine_analytics(graph)
    assert res["total_routines_tracked"] == 2
    assert res["average_streak"] == 4.0
    assert res["max_streak"] == 5
    assert res["consistency_percentage"] == 50.0


def test_gateway_routine_analytics_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/routines/analytics")
    assert resp.status_code == 200
    assert "total_routines_tracked" in resp.json()
