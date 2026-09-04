"""Integration tests for Wearable QR & T-Shirt Studio and Instant Camera Connect.

Validates print-ready SVG vector generation, QR matrix generation,
public profile lookups, and graph proximity vouch recording.
"""

from fastapi.testclient import TestClient
from gateway.main import create_app
from substrate.graph import Graph
from modules.wearables import tshirt_studio


def test_tshirt_studio_module_direct(graph: Graph):
    res = tshirt_studio.generate_tshirt_design(
        graph=graph,
        handle="robert_k",
        name="Robert K.",
        tagline="AI Systems · Surf & Code",
        interests=["AI Systems", "Surfing", "Specialty Coffee"],
        style="streetwear_back"
    )
    assert res["success"] is True
    assert "svg_vector_url" in res
    assert res["svg_vector_url"].startswith("data:image/svg+xml;")
    assert "badge_id" in res
    assert res["print_specs"]["dimensions_mm"] == "300 x 300 mm (Direct to Garment / Screenprint)"

    # Verify entity is stored in graph
    session = graph.session("test", {"*"})
    entity = session.get_entity(res["badge_id"])
    assert entity is not None
    assert entity["attrs"]["handle"] == "robert_k"
    assert entity["attrs"]["name"] == "Robert K."


def test_tshirt_studio_endpoint(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/wearables/tshirt-badge", json={
        "handle": "elena_s",
        "name": "Elena S.",
        "tagline": "Acoustic Ambient Composer & Nomad",
        "interests": ["Music Production", "Modular Synths", "Matcha"],
        "style": "minimal_chest"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["handle"] == "elena_s"
    assert "svg_vector_url" in data
    assert "SCAN TO CONNECT" in data["message"] or "Print-Ready" in data["message"]


def test_public_connect_profile_endpoint(cfg):
    client = TestClient(create_app(cfg))
    # First create a badge
    client.post("/v1/wearables/tshirt-badge", json={
        "handle": "marcus_w",
        "name": "Marcus W.",
        "tagline": "Product Designer & Climber",
        "interests": ["Bouldering", "Figma", "Espresso"]
    })

    # Look up profile
    res = client.get("/v1/connect/profile/marcus_w")
    assert res.status_code == 200
    data = res.json()
    assert data["found"] is True
    assert data["handle"] == "marcus_w"
    assert data["name"] == "Marcus W."
    assert "Bouldering" in data["interests"]


def test_proximity_vouch_scan_endpoint(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/connect/scan-vouch", json={
        "scanner_id": "user_123",
        "scanned_handle": "marcus_w"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["connected"] is True
    assert data["vouched"] is True
    assert "Karma" in data["karma_awarded"]
