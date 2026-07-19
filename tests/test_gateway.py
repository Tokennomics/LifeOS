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


def test_mobile_api_roundtrip(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    # first run: no vision -> create one -> visible
    assert client.get("/v1/vision").json()["visions"] == []
    client.post("/v1/vision", json={"text": "Freedom\n- Ship v0.2\n- Train"})
    assert len(client.get("/v1/vision").json()["visions"]) == 1

    # plan -> numbered week tasks -> log -> retro
    week = client.post("/v1/plan").json()
    assert len(week["tasks"]) == 2
    assert week["tasks"][0]["n"] == 1
    assert client.post("/v1/log", json={"n": 1}).json()["done"]
    assert client.post("/v1/log", json={"n": 99}).status_code == 400
    retro_result = client.post("/v1/retro").json()
    assert retro_result["done"] == 1

    # capture -> graph summary -> export (Law 2)
    client.post("/v1/capture", json={"text": "note to self"})
    graph_summary = client.get("/v1/graph").json()
    assert graph_summary["counts"]["content"] == 1
    assert graph_summary["entities"] > 0
    assert any(r["label"] == "note to self" for r in graph_summary["recent"])
    export = client.get("/v1/export").json()
    assert len(export["entities"]) == graph_summary["entities"]
    assert len(export["observations"]) >= len(export["entities"])

    # today includes events list
    assert client.get("/v1/today").json()["events"] == []


def test_app_is_served(cfg):
    client = TestClient(create_app(cfg))
    assert client.get("/", follow_redirects=False).status_code == 307
    page = client.get("/app/")
    assert page.status_code == 200
    assert "LifeOS" in page.text


def test_router_rules_and_fallback():
    assert route("what's my vision for this year")["module"] == "horizon"
    assert route("capture this thought")["module"] == "voiceos"
    assert route("hello there")["module"] == "chat"
    assert route("hello there")["method"] == "fallback"
