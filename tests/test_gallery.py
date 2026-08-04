import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.comms import gallery
from substrate.graph import Graph


def test_outing_gallery_uploads_and_retrieval(graph: Graph):
    photo_id = gallery.upload_photo(graph, "outing_abc", "alice", "https://img.lifeos/1.jpg")
    assert photo_id is not None

    photos = gallery.list_photos(graph, "outing_abc")
    assert len(photos) == 1
    assert photos[0]["photo_url"] == "https://img.lifeos/1.jpg"


def test_gateway_gallery_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "event_id": "outing_xyz",
        "owner_id": "bob",
        "photo_url": "https://img.lifeos/2.jpg"
    }
    resp_pub = client.post("/v1/comms/gallery", json=payload)
    assert resp_pub.status_code == 200

    resp_list = client.get("/v1/comms/gallery/list?event_id=outing_xyz")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1
