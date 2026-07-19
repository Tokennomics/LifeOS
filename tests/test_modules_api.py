import datetime

from fastapi.testclient import TestClient

from gateway.main import create_app


def _future():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)).isoformat()


def test_full_suite_roundtrip(cfg):
    client = TestClient(create_app(cfg))

    # People / Reconnect
    sam = client.post("/v1/people", json={"name": "Sam"}).json()["person_id"]
    assert client.get("/v1/people").json()["people"][0]["name"] == "Sam"
    draft = client.post("/v1/reconnect/draft", json={"person_id": sam}).json()
    assert "Sam" in draft["text"]
    assert client.post("/v1/reconnect/touch", json={"person_id": sam}).json()["person"] == "Sam"

    # Convoy
    event = client.post("/v1/convoy/event",
                        json={"title": "Gig", "start": _future(), "place": "The Zoo"}).json()["event_id"]
    invite = client.post("/v1/convoy/invite", json={"event_id": event, "person_ids": [sam]}).json()
    assert invite["invited"] == 1
    client.post("/v1/convoy/rsvp", json={"event_id": event, "person_id": sam, "going": True})
    assert client.get("/v1/convoy").json()["events"][0]["yes"] == ["Sam"]
    assert "Gig" in client.get("/v1/convoy/digest").json()["text"]
    attended = client.post("/v1/convoy/attended", json={"event_id": event}).json()
    assert attended["people_touched"] == 1

    # Memento (quest from the attended event, then drop + unlock)
    quest = client.get("/v1/capsules").json()["quests"][0]
    assert quest["event_id"] == event
    client.post("/v1/capsules", json={"text": "what a night", "lat": -27.47, "lon": 153.02,
                                      "place": "The Zoo", "event_id": event})
    listed = client.get("/v1/capsules?lat=-27.47&lon=153.02").json()
    assert listed["quests"] == []
    assert listed["capsules"][0]["locked"] is True
    unlocked = client.post("/v1/capsules/unlock", json={"lat": -27.47, "lon": 153.02}).json()
    assert unlocked["unlocked"] == 1

    # Steward (nothing pending on a healthy graph)
    assert client.post("/v1/admin/scan").json()["created"] == 0
    assert client.get("/v1/admin").json()["items"] == []

    # Vitals / Ledger / Calibre / Hearth
    assert client.get("/v1/vitals").json()["windows"][0]["phase"] == "peak"
    client.post("/v1/ledger", json={"amount": 30, "category": "fun"})
    assert client.get("/v1/ledger").json()["total"] == 30
    decision = client.post("/v1/decisions", json={
        "title": "X", "choice": "Y", "confidence": 0.7, "predicted": "Z"}).json()["decision_id"]
    brier = client.post("/v1/decisions/resolve", json={"decision_id": decision, "happened": True}).json()["brier"]
    assert brier == 0.09
    client.post("/v1/spaces", json={"name": "Home", "member_ids": [sam]})
    assert client.get("/v1/spaces").json()["spaces"][0]["members"] == ["Sam"]

    # bad input -> 400 with detail
    assert client.post("/v1/admin/act", json={"item_id": "x", "action": "explode"}).status_code == 400
    assert client.post("/v1/decisions", json={
        "title": "b", "choice": "c", "confidence": 2.0, "predicted": "d"}).status_code == 400


def test_module_routes_respect_auth(cfg):
    cfg["gateway"]["auth_token"] = "secret"
    client = TestClient(create_app(cfg))
    assert client.get("/v1/people").status_code == 401
    ok = client.get("/v1/people", headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200
