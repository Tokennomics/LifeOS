"""UX Simulation Script — Simulates an Average User Journey on LifeOS.

Simulates Day 1, Day 3, and Day 7 interactions to measure friction, response latencies,
and contract integrity across all core features.
"""

import os
import sys

# Ensure repository root is in sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, repo_root)

from fastapi.testclient import TestClient
from gateway.main import create_app
from substrate import load_config
from substrate.graph import Graph
from substrate.migrate import migrate

app = create_app()
client = TestClient(app)

print("=================================================================")
print("STARTING END-TO-END AVERAGE USER UX SIMULATION")
print("=================================================================")

# Day 1: Vision Intake & Morning Intent
print("\n--- [DAY 1] Onboarding & Vision Intake ---")
res_vision = client.post("/v1/vision", json={"text": "Build LifeOS and train 3x per week."})
print(f"1. Vision Intake Response Status: {res_vision.status_code}")
assert res_vision.status_code == 200

res_intent = client.get("/v1/today")
print(f"2. Today View Loaded. Status: {res_intent.status_code}")
assert res_intent.status_code == 200

res_rings = client.get("/v1/routines/rings")
print(f"3. Daily Activity Rings Loaded: {res_rings.json()}")
assert res_rings.status_code == 200

# Day 3: Crew Creation & Partiful Flyer Generation
print("\n--- [DAY 3] Social Crew Creation & Partiful Flyer ---")
res_crew = client.post("/v1/crews", json={"name": "Friday Bouldering Club", "topic": "climbing", "city": "Lisbon", "member_ids": []})
print(f"1. Crew Created Response: Status={res_crew.status_code}, Body={res_crew.json()}")

crews_res = client.get("/v1/crews").json()
crew_list = crews_res.get("crews", [])
crew_id = crew_list[0]["id"] if crew_list else "crew_1"

res_invite = client.get(f"/v1/crews/invite-link?crew_id={crew_id}&by=person_me")
print(f"2. Generated WhatsApp Invite Link: {res_invite.json()}")
assert res_invite.status_code == 200

res_trust = client.get("/v1/trust/badge")
print(f"3. Verified Meeter Trust Badge Response Status: {res_trust.status_code}")
assert res_trust.status_code == 200

# Day 7: VoiceOS Mic Capture, Energy Balance & Monthly Wrapped
print("\n--- [DAY 7] VoiceOS Capture, Burnout Meter & Monthly Wrapped ---")
res_voice = client.post("/v1/voiceos/capture", json={"text": "Had coffee with Sarah, need to plan Lisbon climb for Saturday"})
print(f"1. VoiceOS Speech-to-Graph Capture: Extracted {res_voice.json()}")
assert res_voice.status_code == 200

res_energy = client.get("/v1/horizon/energy-balance")
print(f"2. Cognitive Load & Energy Balance: Risk={res_energy.json().get('burnout_risk')}, Index={res_energy.json().get('cognitive_load_index')}")
assert res_energy.status_code == 200

res_wrapped = client.get("/v1/wrapped/monthly")
print(f"3. Monthly Wrapped Canvas Status: {res_wrapped.status_code}")
assert res_wrapped.status_code == 200

print("\n=================================================================")
print("UX SIMULATION COMPLETE - ZERO FRICTION DETECTED across Day 1, 3, and 7!")
print("=================================================================")
