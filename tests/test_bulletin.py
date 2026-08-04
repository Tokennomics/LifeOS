import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.comms import bulletin
from substrate.graph import Graph


def test_crew_bulletin_announcements(graph: Graph):
    bulletin_id = bulletin.publish_bulletin(graph, "crew_abc", "Upcoming Climbing Trip", "Meeting at 9am Saturday")
    assert bulletin_id is not None

    announcements = bulletin.list_bulletins(graph, "crew_abc")
    assert len(announcements) == 1
    assert announcements[0]["title"] == "Upcoming Climbing Trip"


def test_gateway_bulletin_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "crew_id": "crew_xyz",
        "title": "Pizza Outing",
        "body": "Friday evening at 7pm"
    }
    resp_pub = client.post("/v1/comms/bulletin", json=payload)
    assert resp_pub.status_code == 200

    resp_list = client.get("/v1/comms/bulletin/list?crew_id=crew_xyz")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1
