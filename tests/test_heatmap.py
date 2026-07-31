import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import heatmap
from substrate.graph import Graph


def test_activity_heatmap_generation(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create event with coordinate attrs and attending list
    session.create_entity(
        "event",
        {
            "title": "Lisbon Sunset Party",
            "lat": 38.715,
            "lng": -9.140,
            "attending": ["user1", "user2", "user3"]
        },
        source="test"
    )
    # Create another event with no coordinates (should be ignored)
    session.create_entity(
        "event",
        {
            "title": "Online Meeting",
            "attending": ["user1"]
        },
        source="test"
    )

    hotspots = heatmap.get_activity_heatmap(graph)
    assert len(hotspots) == 1
    assert hotspots[0]["title"] == "Lisbon Sunset Party"
    assert hotspots[0]["lat"] == 38.715
    assert hotspots[0]["weight"] == 3.0


def test_gateway_heatmap_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/venues/activity-heatmap")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
