"""The six endpoints that asked for hardware, and the one table they refuse out of.

Each of them invented what it could not measure: an HRV and a sleep score from no sensor,
a recovery score from no watch, three named peers over a radio a browser cannot open, four
healthy edge nodes in front of one SQLite file, and a signed app-store manifest from a
process that has never run a build.

These pin three things: that each answers 503 rather than a 200 that reads as a device
which failed to answer, that the refusal says what would actually be needed, and that the
status page's `unavailable` list and those refusals come from the same rows — the drift
between two hand-maintained copies being the reason the constants exist at all.
"""

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.platform import capabilities, overview

PW = "correct-horse-battery"

#: Every route that used to invent hardware, and the capability it now names.
REFUSING = [
    ("/v1/wearables/ambient-whispers", capabilities.WEARABLES),
    ("/v1/wearables/sync-telemetry", capabilities.WEARABLES),
    ("/v1/biometrics/circadian-sync", capabilities.BIOMETRICS),
    ("/v1/mesh/offline-peer-sync", capabilities.MESH),
    ("/v1/infra/edge-replication", capabilities.EDGE),
    ("/v1/native/app-store-manifest", capabilities.NATIVE_BUILD),
]

#: Values the old handlers returned. None of them was measured, and several were the same
#: for every caller on every deployment.
INVENTED = ("hrv_ms", "recovery_score", "sleep_score", "recovery_tier", "telemetry_synced",
            "mesh_active", "edge_mesh_active", "wearables_synced", "manifest_generated",
            "connected_peers", "node_health", "sub_vocal_whispers", "ios_bundle_id",
            "battery_boost", "replication_latency", "social_readiness")


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def world(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


# ---- the table ---------------------------------------------------------------

def test_every_capability_says_why_and_what_it_would_need():
    for name, row in capabilities.UNAVAILABLE.items():
        assert row["why"].strip(), name
        assert row["needs"], name
        assert all(isinstance(need, str) and need.strip() for need in row["needs"]), name


def test_an_unknown_capability_is_a_failure_not_a_plausible_refusal():
    """A typo must not become a confident answer about nothing — that is the same bug as
    the props this replaces, one layer down."""
    with pytest.raises(capabilities.UnknownCapability):
        capabilities.refusal("teleportation")


def test_a_refusal_is_never_partly_available():
    out = capabilities.refusal(capabilities.MESH)
    assert out["available"] is False
    assert out["capability"] == capabilities.MESH
    assert out["why"] and out["needs"]


def test_the_status_page_reads_the_same_rows_as_the_endpoints(graph):
    """The whole point of the module. If the status page kept its own copy, the two would
    disagree the first time somebody edited one of them."""
    listed = {row["name"]: row["why"] for row in overview.system(graph)["unavailable"]}
    assert set(listed) == set(capabilities.UNAVAILABLE)
    for name, row in capabilities.UNAVAILABLE.items():
        assert listed[name] == row["why"]


def test_the_build_files_are_checked_rather_than_asserted(tmp_path):
    real = {row["path"]: row["present"] for row in capabilities.build_files()}
    assert real["surfaces/app/www/manifest.webmanifest"] is True
    assert real["surfaces/app/capacitor.config.json"] is True
    # Pointed somewhere those files are not, every one reports absent rather than present.
    elsewhere = capabilities.build_files(root=str(tmp_path))
    assert all(row["present"] is False for row in elsewhere)


# ---- over HTTP ---------------------------------------------------------------

@pytest.mark.parametrize("path,capability", REFUSING)
def test_hardware_endpoints_refuse_with_503_and_name_the_capability(world, path, capability):
    """503 rather than 400: the caller did nothing wrong. And rather than a 200 carrying
    `synced: false`, which reads as a device that was asked and did not answer."""
    client, people = world
    res = client.post(path, json={}, headers=people["ana"]["h"])
    assert res.status_code == 503, f"{path} answered {res.status_code}"
    detail = res.json()["detail"]
    assert detail["available"] is False
    assert detail["capability"] == capability
    assert detail["why"]
    assert detail["needs"]


@pytest.mark.parametrize("path,capability", REFUSING)
def test_a_refusal_invents_no_reading_and_no_device(world, path, capability):
    """Sending the numbers the old handler echoed back must not produce a reading. The old
    version took `hrv_ms` from the body and reported it as measured."""
    client, people = world
    res = client.post(path, json={"hrv_ms": 82, "recovery_score": 94,
                                  "device": "a watch", "peers": ["someone"],
                                  "platform": "ios_and_android"},
                      headers=people["ana"]["h"])
    assert res.status_code == 503
    body = res.text
    for invented in INVENTED:
        assert invented not in body, f"{path} still reports {invented}"
    assert "82" not in str(res.json()["detail"].get("why", ""))


def test_the_manifest_endpoint_points_at_the_build_rather_than_emitting_one(world):
    client, people = world
    res = client.post("/v1/native/app-store-manifest", json={"platform": "ios_and_android"},
                      headers=people["ana"]["h"])
    assert res.status_code == 503
    detail = res.json()["detail"]
    paths = {row["path"] for row in detail["where"]}
    assert "surfaces/app/android/app/src/main/AndroidManifest.xml" in paths
    assert "surfaces/app/www/manifest.webmanifest" in paths
    assert all(row["present"] for row in detail["where"])
    # The old one handed out two download URLs on a host this deployment does not serve.
    assert "connectos.app" not in res.text
    assert ".ipa" not in res.text and ".aab" not in res.text


def test_the_status_page_and_the_endpoint_agree_over_http(world):
    """Read the two surfaces the way a user would, and compare them."""
    client, people = world
    status = client.post("/v1/os/master-controller", json={}, headers=people["ana"]["h"])
    assert status.status_code == 200
    listed = {row["name"]: row["why"] for row in status.json()["unavailable"]}

    refused = client.post("/v1/mesh/offline-peer-sync", json={},
                          headers=people["ana"]["h"]).json()["detail"]
    assert listed[refused["capability"]] == refused["why"]
