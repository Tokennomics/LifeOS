from fastapi.testclient import TestClient

from gateway.main import create_app
from gateway.router import route


def test_health_and_offline_vision_flow(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    health = client.get("/health").json()
    assert health["ok"] is True
    assert health["env"] == "sqlite"
    assert health["claude"] is False

    routed = client.post("/v1/route", json={"text": "plan my goals for the quarter"}).json()
    assert routed["module"] == "horizon"

    resp = client.post("/v1/vision", json={"text": "Freedom by 40\n- Ship Life OS v0.1\n- Train 3x/week"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "created"
    assert body["goals"] == 2

    assert client.get("/health").json()["entities"] == 3  # vision + 2 goals


def test_auth_enforced_when_token_set(cfg):
    cfg["gateway"]["auth_token"] = "secret"
    app = create_app(cfg)
    client = TestClient(app)
    assert client.post("/v1/route", json={"text": "hi"}).status_code == 401
    ok = client.post("/v1/route", json={"text": "hi"}, headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200  # health stays open


def test_router_rules_and_fallback():
    assert route("what's my vision for this year")["module"] == "horizon"
    assert route("capture this thought")["module"] == "voiceos"
    assert route("hello there")["module"] == "chat"
    assert route("hello there")["method"] == "fallback"
