"""
Performance benchmark and edge-case functional testing suite for ConnectOS.
"""

import time
from fastapi.testclient import TestClient
from gateway.main import create_app

def test_api_latency_benchmarks(cfg):
    client = TestClient(create_app(cfg))

    # Warmup request to initialize route routing
    client.get("/v1/weather/radar")

    endpoints = [
        ("POST", "/v1/synergy/instant-match", {"interest": "coffee"}),
        # `/v1/dating/instant-meet` is not benchmarked here any more: it is gated behind
        # LIFEOS_DATING_ENABLED and a signing key, so on a default config it answers 503 and
        # the only thing being timed is the gate refusing. Its behaviour is covered in
        # tests/test_dating_meets.py, on a surface that is actually switched on.
        ("POST", "/v1/safety/escort", {"destination": "Home", "eta_mins": 20}),
        ("POST", "/v1/ledger/quick-split", {"amount": 50}),
        ("POST", "/v1/synergy/sports-match", {"sport": "climbing"}),
        ("POST", "/v1/synergy/nomad-match", {"domain": "tech"}),
        ("POST", "/v1/synergy/ski-match", {"resort": "Alps"}),
        ("POST", "/v1/synergy/rave-match", {"subgenre": "techno"}),
        ("POST", "/v1/synergy/surf-match", {"spot": "Beach"}),
        ("GET", "/v1/weather/radar", None),
        ("GET", "/v1/developer/plugins", None),
        ("POST", "/v1/developer/plugins/register", {"name": "Test"}),
        ("POST", "/v1/gamification/mint-presence", {"event_name": "Meet"}),
        ("GET", "/v1/vitals/social-battery", None),
        ("GET", "/v1/ar/spatial-flares", None),
        ("POST", "/v1/ai/copilot-icebreaker", {"partner_name": "Alex"}),
        ("POST", "/v1/biometrics/circadian-sync", {"hrv_ms": 70}),
        ("POST", "/v1/ai/squad-agent", {"crew_id": "c1"}),
        ("GET", "/v1/city/live-globe", None),
        # `/v1/zk/verify-attribute` was benchmarked here until it was removed: it answered
        # "verified" to any attribute from any caller, including AGE_OVER_18. Benchmarking
        # how fast a prop responds is the least useful thing to know about it.
        ("GET", "/v1/gamification/streaks", None),
    ]

    for method, path, payload in endpoints:
        # Warmup single call
        if method == "GET":
            client.get(path)
        else:
            client.post(path, json=payload or {})

        start_t = time.perf_counter()
        if method == "GET":
            res = client.get(path)
        else:
            res = client.post(path, json=payload or {})
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        assert res.status_code == 200, f"Endpoint {path} failed with status {res.status_code}"
        assert elapsed_ms < 500.0, f"Endpoint {path} exceeded 500ms latency target ({elapsed_ms:.2f}ms)"

def test_edge_cases_and_null_fallbacks(cfg):
    client = TestClient(create_app(cfg))

    # Empty payload edge cases
    #
    # `matched is True` on an empty payload was the clearest single statement of what was
    # wrong here: no interest, no city, no accounts in the database, and the answer was yes.
    # An unanswerable question now says so instead.
    res1 = client.post("/v1/synergy/instant-match", json={})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False
    assert res1.json()["needs_city"] is True

    # `agreed: True` on an empty body: a confirmed meeting with nobody, complete with an
    # ETA and a security PIN. Agreeing now needs somebody to agree with.
    res2 = client.post("/v1/dating/agree-meet", json={})
    assert res2.status_code == 400

    # An empty body used to start an escort to "Miradouro Rooftop Bar" and report the crew
    # notified. A walk with no destination is not a walk.
    res3 = client.post("/v1/safety/escort", json={})
    assert res3.status_code == 400

    res4 = client.post("/v1/ledger/quick-split", json={})
    assert res4.status_code == 200
    assert res4.json()["per_person"] > 0
