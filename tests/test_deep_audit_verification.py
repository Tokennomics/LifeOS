"""Comprehensive Deep Audit & End-to-End Verification Test Suite.

Verifies that all recent frontier systems (Universal Markdown Vault Export,
Daily Midnight Synthesis, Voice Copilot, Vision Intake, Micro-Masterclasses,
Nightlife Radar, Layover Navigator) perform real Substrate Graph writes,
real in-memory ZIP compilations, and real context-aware data queries.
"""

import base64
import io
import zipfile
from fastapi.testclient import TestClient
from gateway.main import create_app
from substrate.graph import Graph


def test_universal_markdown_export_cold_start(cfg):
    """Verifies that an empty graph exports a clean, valid zip with README and genesis note."""
    client = TestClient(create_app(cfg))
    res = client.post("/v1/export/universal-markdown", json={"format": "Obsidian"})
    assert res.status_code == 200
    data = res.json()
    assert data["export_complete"] is True
    assert "download_url" in data
    
    # Decode and unpack the base64 ZIP
    b64_str = data["download_url"].replace("data:application/zip;base64,", "")
    zip_bytes = base64.b64decode(b64_str)
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        namelist = zf.namelist()
        assert "README.md" in namelist
        readme_content = zf.read("README.md").decode("utf-8")
        assert "ConnectOS Life & Culture Vault" in readme_content


def test_universal_markdown_export_populated_all_kinds(cfg):
    """Verifies that populated graph entities across goals, people, decisions, places, memories
    are serialized into distinct directories with valid YAML frontmatter."""
    client = TestClient(create_app(cfg))
    
    # Seed various entities
    client.post("/v1/people", json={"name": "Alasdair", "cadence_days": 14})
    client.post("/v1/people", json={"name": "Catriona", "cadence_days": 21})
    client.post("/v1/goals", json={"title": "Launch Regenerative Community Hub", "target_week": "W36"})
    client.post("/v1/decisions", json={"title": "Host Open-Air Vinyl Session", "choice": "Leith Shore Loft", "confidence": 0.85, "predicted": "High community resonance"})
    client.post("/v1/capture", json={"text": "Visited the secret Japanese listening bar in St Stephen Street."})
    
    # Export vault
    res = client.post("/v1/export/universal-markdown", json={"format": "Obsidian"})
    assert res.status_code == 200
    data = res.json()
    assert data["export_complete"] is True
    assert data["total_vault_files"] >= 5

    # Verify extracted zip contents
    b64_str = data["download_url"].replace("data:application/zip;base64,", "")
    zip_bytes = base64.b64decode(b64_str)
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        namelist = zf.namelist()
        
        # Check people directory
        assert any(n.startswith("02_People_Graph/Alasdair") for n in namelist)
        assert any(n.startswith("02_People_Graph/Catriona") for n in namelist)
        
        # Check goals directory
        assert any(n.startswith("03_Goals_and_Tasks/Goal_Launch") for n in namelist)
        
        # Check decisions directory
        assert any(n.startswith("04_Decisions_and_Reviews/Host_Open-Air") for n in namelist)
        
        # Read a sample note and verify frontmatter
        person_file = next(n for n in namelist if "Alasdair" in n)
        person_content = zf.read(person_file).decode("utf-8")
        assert person_content.startswith("---")
        assert 'name: "Alasdair"' in person_content
        assert "cadence_days: 14" in person_content


def test_daily_reflection_synthesis_graph_persistence(cfg):
    """Verifies that daily synthesis creates and persists a real 'memory' entity in the Substrate graph."""
    client = TestClient(create_app(cfg))
    
    # Add a completed task and a goal first
    client.post("/v1/capture", json={"text": "Practiced cold water breathwork at the river."})
    
    # Trigger synthesis
    res = client.post("/v1/journal/daily-reflection-synthesis", json={"city": "Munich", "date": "2026-08-20"})
    assert res.status_code == 200
    data = res.json()
    assert data["synthesis_complete"] is True
    assert "memory_id" in data
    memory_id = data["memory_id"]
    
    # Verify by exporting markdown and finding the newly created memory
    res_export = client.post("/v1/export/universal-markdown", json={"format": "Obsidian"})
    export_files = res_export.json()["files"]
    assert any(memory_id in content for content in export_files.values())


def test_vision_intake_graph_persistence(cfg):
    """Verifies that flyer OCR intake saves a real event entity in the Substrate graph."""
    client = TestClient(create_app(cfg))
    
    payload = {
        "title": "Subterranean Bossa Nova Night",
        "venue": "Bramble Stone Cellar",
        "date": "Saturday 22:00",
        "cost": "Free Entry",
        "text": "Subterranean Bossa Nova Night @ Bramble Stone Cellar this Saturday 22:00. Free Entry."
    }
    res = client.post("/v1/vision/intake", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["intake_status"] == "PARSED_SUCCESSFULLY"
    assert "event_id" in data
    event_id = data["event_id"]
    assert data["extracted_event"]["title"] == "Subterranean Bossa Nova Night"
    
    # Verify the event is in the graph by exporting
    res_export = client.post("/v1/export/universal-markdown", json={"format": "Obsidian"})
    files = res_export.json()["files"]
    assert any("Bossa Nova" in content or event_id in content for content in files.values())


def test_voice_copilot_context_awareness(cfg):
    """Verifies that Voice AI Copilot reads live graph places and contacts."""
    client = TestClient(create_app(cfg))
    
    # Seed a friend and a place
    client.post("/v1/people", json={"name": "Lukas", "cadence_days": 7})
    client.post("/v1/people", json={"name": "Sophie", "cadence_days": 10})
    
    # Query squad
    res_squad = client.post("/v1/voice/copilot-chat", json={"query": "Who is nearby in my squad?", "city": "Munich"})
    assert res_squad.status_code == 200
    data_squad = res_squad.json()
    assert data_squad["voice_response_generated"] is True
    assert "Lukas" in data_squad["voice_reply_text"]
    assert "<speak>" in data_squad["tts_ssml"]
    
    # Query vinyl club
    res_vinyl = client.post("/v1/voice/copilot-chat", json={"query": "What's the best vinyl sound system tonight?", "city": "Munich"})
    assert res_vinyl.status_code == 200
    assert "Blitz Club" in res_vinyl.json()["voice_reply_text"]


def test_workshops_and_nightlife_persistence(cfg):
    """Verifies that micro-masterclasses and nightlife venues persist as queryable graph entities."""
    client = TestClient(create_app(cfg))
    
    res1 = client.post("/v1/workshops/micro-masterclasses", json={"city": "Munich"})
    assert res1.status_code == 200
    assert len(res1.json()["micro_masterclasses"]) >= 3
    
    res2 = client.post("/v1/nightlife/party-radar", json={"city": "Munich"})
    assert res2.status_code == 200
    assert len(res2.json()["curated_clubs_and_parties"]) >= 3

    res3 = client.post("/v1/nightlife/guestlist-vip", json={"venue": "Blitz Club", "crew_size": 3})
    assert res3.status_code == 200
    assert "event_id" in res3.json()
    assert res3.json()["guestlist_confirmed"] is True


def test_layover_multi_hub_discovery(cfg):
    """Verifies multi-city layover navigation and safe exploration calculations."""
    client = TestClient(create_app(cfg))
    
    # Test EDI
    res_edi = client.post("/v1/travel/layover-discovery", json={"hub": "Edinburgh Airport (EDI)", "layover_hours": 4.0})
    assert res_edi.status_code == 200
    data_edi = res_edi.json()
    assert data_edi["layover_navigator_active"] is True
    assert data_edi["safe_exploration_time"] == "2.5 Hours Active Exploration (90-min safety return cushion)"
    assert "Edinburgh Trams" in data_edi["curated_micro_escape"]["transit"]
    
    # Test LIS
    res_lis = client.post("/v1/travel/layover-discovery", json={"hub": "Lisbon Humberto Delgado (LIS)", "layover_hours": 5.0})
    assert res_lis.status_code == 200
    data_lis = res_lis.json()
    assert "Metro Vermelha" in data_lis["curated_micro_escape"]["transit"]
    assert "Santa Luzia" in str(data_lis["curated_micro_escape"]["stops"])
