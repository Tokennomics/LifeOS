import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.venues import event_feed
from substrate.graph import Graph


def test_personalized_event_feed(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create interests and events
    session.create_entity("interest", {"name": "climbing"}, source="test")
    session.create_entity("interest", {"name": "sushi"}, source="test")

    session.create_entity("event", {"title": "Indoor Climbing Meetup", "topic": "Sports"}, source="test")
    session.create_entity("event", {"title": "Book Reading Session", "topic": "Literature"}, source="test")

    feed = event_feed.get_personalized_event_feed(graph)
    assert len(feed) >= 2
    # "Indoor Climbing Meetup" matches interest climbing, should be ranked first
    assert feed[0]["title"] == "Indoor Climbing Meetup"
    assert feed[0]["match_score"] > 1.0


def test_gateway_personalized_feed_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/discover/personalized-event-feed")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
