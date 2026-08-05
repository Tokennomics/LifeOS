import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.comms import collage
from substrate.graph import Graph


def test_photo_collage_aggregation(graph: Graph):
    session = graph.session("test", {"*"})
    
    session.create_entity("content", {"type": "shared_photo", "event_id": "outing_123", "photo_url": "https://img.com/1.png", "owner_id": "alice"}, source="test")

    list_photos = collage.create_photo_collage(graph, "outing_123")
    assert len(list_photos) == 1
    assert list_photos[0]["url"] == "https://img.com/1.png"


def test_gateway_collage_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/v1/comms/gallery/collage?event_id=outing_123")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
