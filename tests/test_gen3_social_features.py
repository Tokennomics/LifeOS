"""
Integration test suite for Gen-3 Social OS Platform features.
"""

from fastapi.testclient import TestClient
from gateway.main import create_app

def test_instant_synergy_match(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/synergy/instant-match", json={"interest": "specialty coffee", "timeframe": "30 mins"})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert "Fabrica Coffee Roasters" in data["suggested_venue"]

def test_instant_dating_meet_7factor(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/dating/instant-meet", json={"vibe": "drinks tonight", "timeframe": "next hour"})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert "breakdown" in data
    assert data["breakdown"]["proximity_score"] == 98
    assert data["breakdown"]["trust_index"] == 96

def test_agree_dating_meet(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/dating/agree-meet", json={"partner_name": "Elena R.", "venue": "Miradouro Rooftop"})
    assert res.status_code == 200
    data = res.json()
    assert data["agreed"] is True
    assert data["pin_code"] == "4892"

def test_safewalk_escort(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/safety/escort", json={"destination": "Miradouro Rooftop", "eta_mins": 15})
    assert res.status_code == 200
    data = res.json()
    assert data["active"] is True
    assert data["escort_code"] == "SAFE-8921"

def test_quick_split_expenses(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/ledger/quick-split", json={"title": "Sunset Drinks", "amount": 60.00, "people_count": 4})
    assert res.status_code == 200
    data = res.json()
    assert data["per_person"] == 15.00
    assert "revolut.me" in data["payment_link"]

def test_sports_and_nomad_match(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/synergy/sports-match", json={"sport": "bouldering"})
    assert res1.status_code == 200
    assert res1.json()["sport"] == "bouldering"

    res2 = client.post("/v1/synergy/nomad-match", json={"domain": "tech & design"})
    assert res2.status_code == 200
    assert res2.json()["domain"] == "tech & design"

def test_ski_rave_surf_match(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/synergy/ski-match", json={"resort": "Serra da Estrela"})
    assert res1.status_code == 200
    assert res1.json()["fresh_powder_alert"] is True

    res2 = client.post("/v1/synergy/rave-match", json={"subgenre": "techno"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is True

    res3 = client.post("/v1/synergy/surf-match", json={"spot": "Carcavelos"})
    assert res3.status_code == 200
    assert res3.json()["swell_alert"] is True

def test_weather_radar_and_developer_plugins(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.get("/v1/weather/radar")
    assert res1.status_code == 200
    assert len(res1.json()["active_alerts"]) >= 3

    res2 = client.get("/v1/developer/plugins")
    assert res2.status_code == 200
    assert len(res2.json()["plugins"]) >= 4

    res3 = client.post("/v1/developer/plugins/register", json={"name": "Test Plugin", "category": "Sports"})
    assert res3.status_code == 200
    assert res3.json()["registered"] is True

def test_proof_of_presence_and_social_battery(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/gamification/mint-presence", json={"event_name": "Rooftop Meet"})
    assert res1.status_code == 200
    assert res1.json()["minted"] is True
    assert "POP-" in res1.json()["token_id"]

    res2 = client.get("/v1/vitals/social-battery")
    assert res2.status_code == 200
    assert res2.json()["battery_pct"] == 82

def test_ar_flares_and_copilot_icebreaker(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.get("/v1/ar/spatial-flares")
    assert res1.status_code == 200
    assert len(res1.json()["flares"]) >= 3

    res2 = client.post("/v1/ai/copilot-icebreaker", json={"partner_name": "Elena R."})
    assert res2.status_code == 200
    assert len(res2.json()["icebreakers"]) >= 3

def test_gen3_core_pillars(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/biometrics/circadian-sync", json={"hrv_ms": 65, "sleep_score": 88})
    assert res1.status_code == 200
    assert res1.json()["recovery_tier"] == "HIGH_RECOVERY"

    res2 = client.post("/v1/ai/squad-agent", json={"crew_id": "crw-001"})
    assert res2.status_code == 200
    assert res2.json()["negotiated"] is True

    res3 = client.get("/v1/city/live-globe")
    assert res3.status_code == 200
    assert len(res3.json()["active_cities"]) >= 5

    res4 = client.post("/v1/zk/verify-attribute", json={"attribute": "AGE_OVER_18"})
    assert res4.status_code == 200
    assert res4.json()["verified"] is True
    assert "ZK-" in res4.json()["zk_proof"]

def test_karma_audio_itinerary_and_sos(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.get("/v1/trust/karma-score")
    assert res1.status_code == 200
    assert res1.json()["karma_score"] == 98

    res2 = client.get("/v1/audio/lounge-spaces")
    assert res2.status_code == 200
    assert len(res2.json()["active_lounges"]) >= 2

    res3 = client.post("/v1/ai/micro-itinerary", json={"city": "Lisbon"})
    assert res3.status_code == 200
    assert len(res3.json()["stops"]) >= 3

    res4 = client.post("/v1/safety/emergency-sos", json={"location": "Miradouro"})
    assert res4.status_code == 200
    assert res4.json()["sos_active"] is True

def test_nomad_memory_and_vip(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/nomad/city-switch", json={"target_city": "Tokyo"})
    assert res1.status_code == 200
    assert res1.json()["teleported"] is True

    res2 = client.post("/v1/memories/highlight-reel", json={"title": "Rooftop Party"})
    assert res2.status_code == 200
    assert "CAP-" in res2.json()["capsule_id"]

    res3 = client.post("/v1/events/vip-guestlist", json={"venue": "Miradouro"})
    assert res3.status_code == 200
    assert res3.json()["granted"] is True

def test_leaderboard_mentor_and_squad_routine(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.get("/v1/gamification/leaderboard")
    assert res1.status_code == 200
    assert len(res1.json()["leaderboard"]) >= 4

    res2 = client.post("/v1/synergy/mentor-match", json={"domain": "AI"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is True

    res3 = client.post("/v1/routines/squad-sync", json={"routine_name": "Dawn Patrol Surf"})
    assert res3.status_code == 200
    assert res3.json()["synced"] is True

def test_settle_photo_wall_and_quests(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/ledger/settle-up", json={"amount": 22.50})
    assert res1.status_code == 200
    assert res1.json()["settled"] is True

    res2 = client.get("/v1/gallery/live-event-wall")
    assert res2.status_code == 200
    assert len(res2.json()["active_photos"]) >= 2

    res3 = client.post("/v1/quests/city-discovery", json={"city": "Lisbon"})
    assert res3.status_code == 200
    assert "QST-" in res3.json()["quest_id"]

def test_transparent_algo_and_revenue_share(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/feed/transparent-rules", json={"real_world_weight": 0.85})
    assert res1.status_code == 200
    assert res1.json()["applied"] is True

    res2 = client.post("/v1/growth/habit-stacking", json={"anchor_habit": "Espresso"})
    assert res2.status_code == 200
    assert res2.json()["stacked"] is True

    res3 = client.get("/v1/safety/community-grid")
    assert res3.status_code == 200
    assert res3.json()["grid_status"] == "NORMAL_OPERATION"

    res4 = client.get("/v1/economics/revenue-share")
    assert res4.status_code == 200
    assert res4.json()["earnings_to_date"] == 145.00

def test_monetization_perks_and_subscriptions(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.get("/v1/monetization/sponsored-perks")
    assert res1.status_code == 200
    assert len(res1.json()["perks"]) >= 2

    res2 = client.post("/v1/billing/subscriptions", json={"plan": "EXPLORER_PRO"})
    assert res2.status_code == 200
    assert res2.json()["subscribed"] is True
    assert res2.json()["price_eur"] == 9.99

def test_voice_brief_gifting_and_wellness(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/ai/voice-brief", json={"transcript": "Coffee at 4 PM then drinks"})
    assert res1.status_code == 200
    assert res1.json()["processed"] is True

    res2 = client.post("/v1/ledger/gift-coffee", json={"recipient": "Elena R.", "amount": 3.80})
    assert res2.status_code == 200
    assert res2.json()["gifted"] is True

    res3 = client.get("/v1/vitals/social-wellness")
    assert res3.status_code == 200
    assert res3.json()["flourishing_score"] == 92
