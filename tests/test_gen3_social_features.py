"""
Integration test suite for Gen-3 Social OS Platform features.
"""

from fastapi.testclient import TestClient
from gateway.main import create_app

def test_instant_synergy_match(cfg):
    """Used to assert Elena R. was found at Fabrica Coffee Roasters, on an empty database,
    for every caller. On an empty database the true answer is that nobody is there."""
    client = TestClient(create_app(cfg))
    res = client.post("/v1/synergy/instant-match",
                      json={"city": "Lisbon", "interest": "specialty coffee"})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is False
    assert data["people"] == []
    assert "suggested_venue" not in data

def test_instant_dating_meet_7factor(cfg):
    """The "7-Factor Comprehensive Match Engine" was seven constants -- proximity 98, trust
    index 96 and five more -- weighted into a score and attached to Elena R., 1.2 km away.
    There was no distance, because there were no coordinates, and no Elena."""
    client = TestClient(create_app(cfg))
    res = client.post("/v1/dating/instant-meet",
                      json={"city": "Lisbon", "vibe": "drinks tonight"})
    assert res.status_code in (200, 503)      # 503 when the dating surface is off
    data = res.json()
    assert "breakdown" not in data
    assert "partner_name" not in data

def test_agree_dating_meet(cfg):
    """Typing a name into a box returned `agreed: True`, an ETA, a map pin and PIN 4892 --
    the same four digits for every pair in the world -- with nobody on the other end.
    Agreeing now requires an account to agree with."""
    client = TestClient(create_app(cfg))
    res = client.post("/v1/dating/agree-meet",
                      json={"partner_name": "Elena R.", "venue": "Miradouro Rooftop"})
    assert res.status_code == 400
    assert "4892" not in res.text

def test_safewalk_escort(cfg):
    client = TestClient(create_app(cfg))
    # `SAFE-8921` was the same code for every walk in the world, and "Crew notified" was a
    # sentence with no message behind it. A walk is a real row with a real deadline now, and
    # it says plainly that nothing was sent.
    res = client.post("/v1/safety/escort", json={"destination": "Miradouro Rooftop",
                                                 "eta_mins": 15})
    assert res.status_code == 200
    data = res.json()
    assert data["watching"] is True
    assert data["push_delivered"] is False and data["can_see_it"] == 0
    assert "SAFE-8921" not in res.text

def test_quick_split_expenses(cfg):
    # This used to assert the payment link — `"revolut.me" in data["payment_link"]` — which
    # pinned the defect in place: a link to somebody else's payment service, carrying the
    # amount in a query string, for an account nobody had connected. Splitting stores a real
    # tab now, and a headcount with nobody named is the calculator, which says so.
    client = TestClient(create_app(cfg))
    res = client.post("/v1/ledger/quick-split",
                      json={"title": "Sunset Drinks", "amount": 60.00, "people_count": 4})
    assert res.status_code == 200
    data = res.json()
    assert data["each"] == 15.00
    assert data["recorded"] is False
    assert "revolut" not in res.text.lower()

def test_sports_and_nomad_match(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/synergy/sports-match", json={"sport": "bouldering"})
    assert res1.status_code == 200
    assert res1.json()["sport"] == "bouldering"

    res2 = client.post("/v1/synergy/nomad-match", json={"domain": "tech & design"})
    assert res2.status_code == 200
    assert res2.json()["domain"] == "tech & design"

def test_ski_rave_surf_match(cfg):
    """`fresh_powder_alert: True` and `swell_alert: True` were literals — they fired in July
    in Lisbon. Nothing measures snow or swell here, so the endpoints say so."""
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/synergy/ski-match", json={"city": "Lisbon", "resort": "Serra da Estrela"})
    assert res1.status_code == 200
    assert res1.json()["conditions"]["available"] is False

    res2 = client.post("/v1/synergy/rave-match", json={"city": "Lisbon", "subgenre": "techno"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False

    res3 = client.post("/v1/synergy/surf-match", json={"city": "Lisbon", "spot": "Carcavelos"})
    assert res3.status_code == 200
    assert res3.json()["conditions"]["available"] is False

def test_weather_radar_and_developer_plugins(cfg):
    client = TestClient(create_app(cfg))
    # A 2.2 m swell, 45 cm of fresh snowfall and a clear 24 C sky — constants, in July, in
    # Lisbon, for everyone. It takes a city now, because weather is a fact about a place.
    res1 = client.get("/v1/weather/radar")
    assert res1.status_code == 200
    assert res1.json()["needs_city"] is True
    assert "active_alerts" not in res1.json()

    # Four plugins with developers and ratings out of five, on an empty database.
    res2 = client.get("/v1/developer/plugins")
    assert res2.status_code == 200
    assert res2.json()["plugins"] == []

    # Registration returned success and stored nothing, so a developer would register, see
    # it work, and never find their plugin again. It validates a manifest now, which needs
    # a version and scopes — a name alone is not a manifest.
    res3 = client.post("/v1/developer/plugins/register",
                       json={"name": "Test Plugin", "category": "Sports"})
    assert res3.status_code == 400

    res3b = client.post("/v1/developer/plugins/register",
                        json={"name": "Test Plugin", "version": "1.0.0",
                              "scopes": ["content:read"]})
    assert res3b.status_code == 200 and res3b.json()["registered"] is True

def test_proof_of_presence_and_social_battery(cfg):
    client = TestClient(create_app(cfg))
    # It minted a "POP-" token: nobody issued it, it sits on no chain, it verifies nothing.
    # The real idea underneath is a check-in, and that is what it records.
    res1 = client.post("/v1/gamification/mint-presence", json={"event_name": "Rooftop Meet"})
    assert res1.status_code == 200
    assert res1.json()["minted"] is False
    assert "POP-" not in res1.text

    # This used to assert `battery_pct == 82` — the literal the handler returned to every
    # account on the instance, forever. A test that pins a prop in place is how the prop
    # survives review. The battery is computed from real outings now, so a fresh account
    # with nothing logged says it does not know rather than picking a cheerful number.
    res2 = client.get("/v1/vitals/social-battery")
    assert res2.status_code == 200
    assert res2.json()["state"] == "unknown"
    assert res2.json()["recent_outings"] == 0

def test_ar_flares_and_copilot_icebreaker(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.get("/v1/ar/spatial-flares")
    assert res1.status_code == 200
    assert len(res1.json()["flares"]) >= 3

    # Three sentences about a washed Ethiopian pour-over at Fabrica, for whatever name you
    # sent — including one you typed yourself. An opener is only worth sending when it
    # points at something you both actually published, so with no match there is nothing.
    res2 = client.post("/v1/ai/copilot-icebreaker", json={"partner_name": "Elena R."})
    assert res2.status_code == 200
    assert res2.json()["openers"] == []
    assert res2.json()["grounded_in"] == []

def test_gen3_core_pillars(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/biometrics/circadian-sync", json={"hrv_ms": 65, "sleep_score": 88})
    assert res1.status_code == 200
    assert res1.json()["recovery_tier"] == "HIGH_RECOVERY"

    # Reported it had negotiated five calendars and confirmed Alex, Elena R., Marcus T. and
    # Sophia K. There are no calendars, no booking and no payment rail — now stated.
    res2 = client.post("/v1/ai/squad-agent", json={"crew_id": "crw-001"})
    assert res2.status_code == 200
    assert res2.json()["plans"] == []
    assert "calendar negotiation" in res2.json()["not_included"]

    res3 = client.get("/v1/city/live-globe")
    assert res3.status_code == 200
    assert len(res3.json()["active_cities"]) >= 5

    # `/v1/zk/verify-attribute` is gone, and this test is the reason it lasted: it asserted
    # that an AGE_OVER_18 check returns verified=True, which the endpoint did for every
    # attribute from every caller with a random "ZK-" string attached. The route must stay
    # gone — an age claim the app displays as proven is the one prop that can hurt somebody.
    assert client.post("/v1/zk/verify-attribute",
                       json={"attribute": "AGE_OVER_18"}).status_code == 404

def test_karma_audio_itinerary_and_sos(cfg):
    client = TestClient(create_app(cfg))
    # Was `karma_score == 98` — returned to every account on the instance, including one
    # created a second earlier. There is no score now: nobody rates anybody in this app, so
    # a number out of 100 could only ever have been invented.
    res1 = client.get("/v1/trust/karma-score")
    assert res1.status_code == 200
    assert res1.json()["outings_attended"] == 0 and res1.json()["empty"] is True

    res2 = client.get("/v1/audio/lounge-spaces")
    assert res2.status_code == 200
    assert len(res2.json()["active_lounges"]) >= 2

    # Fabrica, Miradouro and Lux Frágil — the same three venues for every user in every
    # city, on an empty database.
    res3 = client.post("/v1/ai/micro-itinerary", json={"city": "Lisbon"})
    assert res3.status_code == 200
    assert res3.json()["stops"] == [] and res3.json()["empty"] is True

    # `recipients_notified: 4` and an emergency PIN, with nothing sent anywhere.
    res4 = client.post("/v1/safety/emergency-sos", json={"location": "Miradouro"})
    assert res4.status_code == 200
    assert res4.json()["severity"] == "sos"
    assert res4.json()["push_delivered"] is False

def test_nomad_memory_and_vip(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/nomad/city-switch", json={"target_city": "Tokyo"})
    assert res1.status_code == 200
    assert res1.status_code == 200

    res2 = client.post("/v1/memories/highlight-reel", json={"title": "Rooftop Party"})
    assert res2.status_code == 200
    assert "CAP-" in res2.json()["capsule_id"]

    res3 = client.post("/v1/events/vip-guestlist", json={"venue": "Miradouro"})
    assert res3.status_code == 200
    assert res3.json()["granted"] is True

def test_leaderboard_mentor_and_squad_routine(cfg):
    client = TestClient(create_app(cfg))
    # The leaderboard ranked "You" #1 above three people who do not exist. Removed on its
    # merits as well as its honesty: ranking people by outings attended rewards performative
    # meeting-up, and publishing one person's activity count to everyone else is the
    # presence-list problem wearing a scoreboard.
    assert client.get("/v1/gamification/leaderboard").status_code == 404

    # Dr. Sarah Lin, ex-YC founder, 97% match, was not a person. With nobody offering AI
    # mentorship in the city, there is no mentor to name.
    res2 = client.post("/v1/synergy/mentor-match", json={"city": "Lisbon", "domain": "AI"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False
    assert "mentor_name" not in res2.json()

    res3 = client.post("/v1/routines/squad-sync", json={"routine_name": "Dawn Patrol Surf"})
    assert res3.status_code == 200
    assert res3.json()["synced"] is True

def test_settle_photo_wall_and_quests(cfg):
    client = TestClient(create_app(cfg))
    # It reported €22.50 settled with "Elena R." and "Alex M." on an account that had split
    # nothing with anybody, and offered a revolut.me link for an unconnected account.
    # Settling needs a real balance owed to a real person.
    res1 = client.post("/v1/ledger/settle-up", json={"counterparty": "nobody"})
    assert res1.status_code == 400
    assert "revolut" not in res1.text.lower()

    res2 = client.get("/v1/gallery/live-event-wall")
    assert res2.status_code == 200
    assert len(res2.json()["active_photos"]) >= 2

    # It minted a quest id and three invented landmarks with point values. It draws on the
    # two things a city really holds now: places seeded from OSM, and plans people proposed.
    res3 = client.post("/v1/quests/city-discovery", json={"city": "Lisbon"})
    assert res3.status_code == 200
    assert res3.json()["places"] == [] and res3.json()["happening"] == []
    assert "QST-" not in res3.text

def test_transparent_algo_and_revenue_share(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/feed/transparent-rules", json={"real_world_weight": 0.85})
    assert res1.status_code == 200
    assert res1.json()["applied"] is True

    # Reported an 89% adherence rate for a stack it had just invented. It creates a real
    # routine now — with the anchor as the trigger — and needs both halves to do it.
    res2 = client.post("/v1/growth/habit-stacking", json={"anchor_habit": "Espresso"})
    assert res2.status_code == 400
    res2b = client.post("/v1/growth/habit-stacking",
                        json={"anchor_habit": "Espresso", "new_habit": "Ten pages"})
    assert res2b.status_code == 200 and res2b.json()["routine_id"]

    # A grid of invented safe houses and volunteer counts. The real grid is who named you.
    res3 = client.get("/v1/safety/community-grid")
    assert res3.status_code == 200
    assert res3.json()["walks"] == []

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
    # There is no speech-to-text in this app and there never was: the endpoint defaulted
    # the transcript for you and returned two venues that appeared in no note.
    res1 = client.post("/v1/ai/voice-brief", json={"transcript": "Coffee at 4 PM then drinks"})
    assert res1.status_code == 200
    assert res1.json()["speech_to_text"] is False
    assert res1.json()["available"] is False        # no ANTHROPIC_API_KEY in tests

    # It returned `voucher_code: "GIFT-FLATWHITE-99"` — the same code for every gift, good
    # at no counter anywhere. The promise is the real part, and it goes on the tab as owed.
    res2 = client.post("/v1/ledger/gift-coffee",
                       json={"recipient": "elena", "amount": 3.80})
    assert res2.status_code == 200
    assert res2.json()["recorded"] is True
    assert res2.json()["money_moved"] is False
    assert "voucher" not in res2.text.lower()

    res3 = client.get("/v1/vitals/social-wellness")
    assert res3.status_code == 200
    assert res3.status_code == 200

def test_sustainable_multi_revenue_monetization(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.get("/v1/monetization/venue-commissions")
    assert res1.status_code == 200
    assert res1.json()["monthly_commission_eur"] == 380.00

    res2 = client.post("/v1/monetization/b2b-team-tier", json={"company_name": "Acme AI", "seats": 25})
    assert res2.status_code == 200
    assert res2.json()["registered"] is True
    assert res2.json()["mrr_eur"] == 374.75

    res3 = client.get("/v1/monetization/plugin-revshare")
    assert res3.status_code == 200
    assert res3.status_code == 200

def test_viral_growth_and_traction(cfg):
    client = TestClient(create_app(cfg))
    # `invite_code: "CREW-LISBON-8921"` was the same string on every instance, and the
    # response promised 100 karma and a free-coffee voucher for sharing it. A link now has
    # to let somebody into a crew that exists, so with no crew there is nothing to mint.
    res1 = client.post("/v1/viral/invite-crew", json={"crew_id": "no-such-crew"})
    assert res1.status_code == 400
    assert "karma" not in res1.text.lower() and "voucher" not in res1.text.lower()

    # Was a fixed 7 for everybody. Counted from real activity now, so a fresh account is 0.
    res2 = client.get("/v1/gamification/streaks")
    assert res2.status_code == 200
    assert res2.json()["current_streak_days"] == 0 and res2.json()["empty"] is True

    # `story_card_url` pointed at a PNG on connectos.app that nothing ever rendered. The
    # card is drawn here now, as an SVG, because nothing in this app rasterises images.
    res3 = client.post("/v1/viral/social-share", json={"title": "Rooftop Party"})
    assert res3.status_code == 200
    assert res3.json()["svg"].startswith("<svg")
    assert "connectos.app" not in res3.text

    res4 = client.get("/v1/community/ambassadors")
    assert res4.status_code == 200
    assert len(res4.json()["cities"]) >= 4

def test_automated_data_ingestion(cfg):
    client = TestClient(create_app(cfg))
    # Listed items ingested from the Google Places API, Eventbrite and Luma, none of which
    # this app integrates. Operator-only now, because it writes public rows and calls out to
    # a volunteer-run service.
    res1 = client.post("/v1/city/sync-live-events", json={"city": "Lisbon"})
    assert res1.status_code == 200
    assert "total_ingested" not in res1.json()
    assert set(res1.json()) >= {"places", "feeds", "conditions"}

def test_zero_friction_convenience_features(cfg):
    client = TestClient(create_app(cfg))
    # Scanned any string and awarded bonus karma. A check-in is your own record now, and it
    # is what makes "outings attended" true rather than asserted.
    res1 = client.post("/v1/events/qr-checkin", json={"qr_code": "QR-FABRICA-4"})
    assert res1.status_code == 200
    assert res1.json()["checked_in"] is True
    assert "bonus_karma" not in res1.json()

    # `SPOT_PRE_RESERVED` for a Wednesday surf that did not exist. Joining is a public act
    # with somebody expecting you; nothing does it on your behalf.
    res2 = client.post("/v1/ai/smart-autorsvp", json={"rule": "Wednesdays 7 AM Surf"})
    assert res2.status_code == 200
    assert res2.json()["auto_joined"] is False
    assert res2.json()["matches"] == []

    res3 = client.post("/v1/events/apple-wallet-pass", json={"event_name": "Rooftop Party"})
    assert res3.status_code == 200
    assert res3.json()["pass_generated"] is True

def test_solo_festival_and_camping_features(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/festivals/solo-camp-crew", json={"city": "Lisbon", "festival_name": "Boom Festival 🎪"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/festivals/carpool-split", json={"city": "Lisbon", "festival_name": "Primavera Sound"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/festivals/stage-flare", json={"city": "Lisbon", "set_name": "Bicep Live Set 🎵"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_layover_gym_and_pet_verticals(cfg):
    client = TestClient(create_app(cfg))
    # Elena R. was in every airport and Alex M. spotted everyone at 96%.
    res1 = client.post("/v1/travel/layover-buddy", json={"airport_code": "LIS"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False
    assert "buddy_name" not in res1.json()

    res2 = client.post("/v1/sports/gym-spotter",
                       json={"city": "Lisbon", "gym": "Vertical Wall"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False
    assert "spotter_name" not in res2.json()

    res3 = client.post("/v1/pets/dog-walk-crew", json={"city": "Lisbon", "park": "Estrela Park"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_language_swap(cfg):
    """Inês M. was matched to everyone who asked, at 98%, forever."""
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/synergy/language-swap",
                       json={"city": "Lisbon", "speak": "English", "learn": "Portuguese"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False
    assert "partner_name" not in res1.json()

def test_human_deep_needs_features(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/housing/co-living-match", json={"city": "Lisbon"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/dining/supper-club", json={"city": "Lisbon", "cuisine": "Tapas"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/wellness/digital-detox", json={"city": "Lisbon", "duration": "2 Hours"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_circular_economy_features(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/economy/barter-swap", json={"city": "Lisbon", "offering": "Surf Lesson", "seeking": "Portuguese"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/economy/community-borrow", json={"city": "Lisbon", "item": "Camping Tent"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/economy/time-bank", json={"city": "Lisbon", "service": "Bicycle repair", "hours": 1})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_group_collab_and_micro_grants(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/routing/group-nav", json={"route_name": "Sunset Walk"})
    assert res1.status_code == 200
    assert res1.json()["navigation_active"] is True

    res2 = client.post("/v1/music/squad-jukebox", json={"city": "Lisbon", "venue": "Fabrica Coffee"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/community/micro-grants", json={"project": "Rescue Stand"})
    assert res3.status_code == 200
    assert res3.json()["grant_voted"] is True

def test_popup_jam_film_and_eco_clean(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/creatives/pop-up-jam", json={"city": "Lisbon", "instrument": "Guitar"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/memories/analog-film-swap", json={"outing_id": "OUTING-8821"})
    assert res2.status_code == 200
    assert res2.json()["film_roll_synced"] is True

    res3 = client.post("/v1/impact/eco-clean-crew", json={"city": "Lisbon", "beach": "Carcavelos"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_global_bridge_beacon_and_residency(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/culture/global-bridge", json={"city_a": "Lisbon", "city_b": "Tokyo"})
    assert res1.status_code == 200
    assert res1.status_code == 200

    # It claimed to broadcast a live location to four trusted members. There is no
    # background location in a PWA, so a watch carries a destination you typed.
    res2 = client.post("/v1/safety/squad-beacon", json={"location": "Cais do Sodre"})
    assert res2.status_code == 200
    assert res2.json()["watching"] is True and res2.json()["push_delivered"] is False

    res3 = client.post("/v1/culture/creator-residency", json={"city": "Lisbon", "creator_name": "Lucas V."})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_ai_butler_magic_split_and_house_swap(cfg):
    client = TestClient(create_app(cfg))
    # The old handler substring-matched the request: "fringe" returned a five-stop
    # Edinburgh week with Kirsty the master distiller, "munich" returned Felix the river
    # surfer. Three hand-written itineraries behind a keyword check, called synthesis.
    res1 = client.post("/v1/ai/outing-butler", json={"weekend": "Saturday"})
    assert res1.status_code == 200
    assert res1.json()["stops"] == []

    res2 = client.post("/v1/payments/one-tap-settle", json={"bill_total": "€84.00", "members_count": 4})
    assert res2.status_code == 200
    assert res2.json()["split_settled"] is True

    res3 = client.post("/v1/housing/nomad-house-swap", json={"city": "Lisbon", "home_city": "Lisbon", "destination_city": "Tokyo"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_comedy_market_and_sunset_sailing(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/culture/secret-comedy", json={"city": "Lisbon", "venue": "Alfama Cellar"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/dining/market-cookoff", json={"city": "Lisbon", "market": "Mercado da Ribeira"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/outdoors/sunset-sailing", json={"city": "Lisbon", "harbor": "Belem"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_reading_cold_plunge_and_art_crawl(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/culture/silent-reading", json={"city": "Lisbon", "loft": "Alfama Loft"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/wellness/cold-plunge", json={"city": "Lisbon", "beach": "Cais do Ginjal"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/creatives/art-crawl", json={"city": "Lisbon", "district": "Santos"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_developer_platform_apikeys_webhooks_and_sandbox(cfg):
    client = TestClient(create_app(cfg))
    # The key is a real credential now: the secret is returned once, hashed at rest, and
    # presenting it authenticates the account that issued it.
    res1 = client.post("/v1/developers/api-keys", json={"app_name": "Wind Radar"})
    assert res1.status_code == 200
    assert res1.json()["secret"].startswith("los_sk_")

    # A subscription needs events, and an event this app never emits is refused at subscribe
    # time rather than accepted and never fired.
    res2 = client.post("/v1/developers/webhooks",
                       json={"target_url": "https://api.myapp.com/webhooks"})
    assert res2.status_code == 400

    res2b = client.post("/v1/developers/webhooks",
                        json={"target_url": "https://api.myapp.com/webhooks",
                              "events": ["meetup.created"]})
    assert res2b.status_code == 200
    assert res2b.json()["signing_secret"].startswith("los_wh_")

    # It reported a passing simulation and a store publication for any id at all.
    res3 = client.post("/v1/developers/plugin-sandbox",
                       json={"manifest": {"name": "Radar", "version": "1.0.0",
                                          "scopes": ["events:read"]}})
    assert res3.status_code == 200
    assert res3.json()["executed"] is False and res3.json()["published"] is False

def test_sauna_plant_swap_and_wine_tasting(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/wellness/sauna-social", json={"city": "Lisbon", "venue": "Alfama Nordic Sauna"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/economy/plant-swap", json={"city": "Lisbon", "park": "Jardim da Estrela"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/dining/wine-tasting", json={"city": "Lisbon", "rooftop": "Miradouro"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_frontier_stack_all_four_engines(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/native/app-store-manifest", json={"platform": "ios_and_android"})
    assert res1.status_code == 200
    assert res1.json()["manifest_generated"] is True

    res2 = client.post("/v1/wearables/sync-telemetry", json={"device": "Apple Watch Ultra", "hrv_ms": 82, "recovery_score": 94})
    assert res2.status_code == 200
    assert res2.json()["telemetry_synced"] is True

    res3 = client.post("/v1/infra/edge-replication", json={"primary_region": "eu-central"})
    assert res3.status_code == 200
    assert res3.json()["edge_mesh_active"] is True

    res4 = client.post("/v1/ai/agent-negotiator", json={"topic": "Weekend Sunset Surf"})
    assert res4.status_code == 200
    assert res4.json()["plans"] == []

def test_city_seeding_and_cold_start_engine(cfg):
    client = TestClient(create_app(cfg))
    # "48 curated third-places & 4 calendar feeds auto-seeded", for any city. It seeds from
    # OpenStreetMap now; with no network in tests, nothing is added and it says so rather
    # than reporting a number.
    res1 = client.post("/v1/seeding/city-bootstrap", json={"city": "Lisbon"})
    assert res1.status_code == 200
    assert res1.json()["empty"] is True
    assert "curated_third_places" not in res1.json()

    # It minted "City Pioneer #042" — the number came from the request body — with a year
    # of free VIP and complimentary coffee at partner roasters. Being early is counted from
    # real rows now, and unlocks nothing; an account that has posted nothing is not in it.
    res2 = client.post("/v1/seeding/pioneer-pass", json={"city": "Lisbon"})
    assert res2.status_code == 200
    assert res2.json()["you_are_here"] is False
    assert res2.json()["no_perks"]

    # Three "golden tickets" behind one shared connectos.app link, with a 1-tap Apple Pay
    # split this app cannot perform. They are separate single-use invites now, so they need
    # a real crew to admit somebody to.
    res3 = client.post("/v1/seeding/golden-tickets", json={"crew_id": "no-such-crew"})
    assert res3.status_code == 400
    assert "apple pay" not in res3.text.lower()

    res4 = client.post("/v1/seeding/anchor-outings", json={"city": "Lisbon"})
    assert res4.status_code == 200
    assert res4.json()["anchors_active"] is True

def test_stripe_and_paypal_payment_gateways(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/payments/stripe/checkout-session", json={"amount": 21.00, "description": "Catamaran Split"})
    assert res1.status_code == 200
    assert res1.json()["session_created"] is True

    res2 = client.post("/v1/payments/stripe/webhook", json={"type": "checkout.session.completed"})
    assert res2.status_code == 200
    assert res2.json()["webhook_processed"] is True

    res3 = client.post("/v1/payments/paypal/create-order", json={"amount": 21.00, "item": "Catamaran Split"})
    assert res3.status_code == 200
    assert res3.json()["order_created"] is True

    res4 = client.post("/v1/payments/paypal/capture-order", json={"order_id": "PAYPAL-ORDER-882194A"})
    assert res4.status_code == 200
    assert res4.json()["order_captured"] is True

def test_automated_city_content_pipeline_and_weather_triggers(cfg):
    client = TestClient(create_app(cfg))
    # "284 events ingested" from Luma, Resident Advisor, Eventbrite and Dice.fm. What this
    # app actually has is ICS venue feeds and Ticketmaster, and it reports what each returned.
    res1 = client.post("/v1/seeding/auto-event-pipeline", json={"city": "Lisbon"})
    assert res1.status_code == 200
    assert "events_ingested" not in res1.json()
    assert res1.json()["provider"]["status"] == "not_configured"

    # A hand-written itinerary, presented as synthesis. Same real answer as
    # /v1/ai/micro-itinerary, which is what this always claimed to be.
    res2 = client.post("/v1/seeding/ai-outing-synthesizer", json={"city": "Lisbon"})
    assert res2.status_code == 200
    assert res2.json()["stops"] == [] and res2.json()["empty"] is True

    # "160 Verified Third Places", with a live_status claiming opening hours and wi-fi
    # speeds were verified, for every city. Nothing was stored and nothing was verified.
    res3 = client.post("/v1/seeding/third-places-directory", json={"city": "Lisbon"})
    assert res3.status_code == 200
    assert res3.json()["verified"] is False
    assert "total_third_places" not in res3.json()

    # It published a dawn-patrol surf squad at Carcavelos in a 4 ft swell, as a literal.
    # With no weather source reachable in tests, nothing is claimed.
    res4 = client.post("/v1/seeding/weather-triggers", json={"city": "Lisbon"})
    assert res4.status_code == 200
    assert res4.json()["available"] is False and res4.json()["triggers"] == []

def test_multi_hobby_passion_content_hubs(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/hobbies/sports-outdoors", json={"city": "Lisbon"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/hobbies/creative-making", json={"city": "Lisbon"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/hobbies/gaming-strategy", json={"city": "Lisbon"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res4 = client.post("/v1/hobbies/culinary-craft", json={"city": "Lisbon"})
    assert res4.status_code == 200
    assert res4.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_landmark_mega_festival_radar(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/events/landmark-radar", json={"city": "Edinburgh", "month": "August"})
    assert res1.status_code == 200
    assert res1.json()["landmark_radar_active"] is True
    assert res1.json()["total_landmark_events"] >= 4

    res2 = client.post("/v1/events/landmark-radar", json={"city": "Munich", "month": "September"})
    assert res2.status_code == 200
    assert res2.json()["landmark_radar_active"] is True

    res3 = client.post("/v1/events/landmark-radar", json={"city": "Lisbon", "month": "June"})
    assert res3.status_code == 200
    assert res3.json()["landmark_radar_active"] is True

def test_frontier_voice_nfc_culture_and_dao(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/voice/crew-huddle", json={"event_name": "Fringe Festival"})
    assert res1.status_code == 200
    assert res1.json()["huddle_active"] is True

    # A "NFC & Apple NameDrop Ephemeral Handshake" reporting 94% compatibility with a named
    # stranger, for any peer string. A web app speaks none of that; sending no code shows
    # yours instead, which two people standing together can read aloud.
    res2 = client.post("/v1/nfc/tap-to-synergy", json={"peer": "Catriona"})
    assert res2.status_code == 200
    body = res2.json()
    assert len(body["code"]) == 6
    # Checked by shape, not by searching the text: the response explains that a web app
    # cannot speak NFC or NameDrop, so those words are legitimately present — and the code
    # alphabet contains 9 and 4, which would make `"94" not in text` a rare flake.
    for invented in ("handshake_verified", "synergy_score", "zk_card_exchanged",
                     "haptic_feedback", "mutual_connections", "shared_hobbies"):
        assert invented not in body

    # Four Scottish words in a dict — braw, scran, dreich, wee — returned for every city on
    # earth, with an etiquette tip about buying rounds. It is the one endpoint here that
    # genuinely needs a key, so it reports unavailable rather than shrinking the lie.
    res3 = client.post("/v1/ai/culture-bridge-translator",
                       json={"city": "Edinburgh", "phrase": "it's a wee bit dreich"})
    assert res3.status_code == 200
    assert res3.json()["available"] is False
    assert "braw" not in res3.text

    res4 = client.post("/v1/dao/community-treasury", json={"city": "Edinburgh"})
    assert res4.status_code == 200
    assert res4.json()["treasury_synced"] is True

def test_anti_boredom_and_genuine_fulfillment_engine(cfg):
    client = TestClient(create_app(cfg))
    # Five quests with invented hosts and crew sizes.
    res1 = client.post("/v1/ai/spontaneous-quests", json={"city": "Edinburgh"})
    assert res1.status_code == 200
    assert res1.json()["quests"] == []

    # `fulfillment_score: 87`, plus four ikigai pillars written on the user's behalf. A
    # graph of meetups cannot measure whether a life is aligned with its purpose.
    res2 = client.post("/v1/ai/ikigai-compass", json={})
    assert res2.status_code == 200
    assert "fulfillment_score" not in res2.json()
    assert res2.json()["no_score"]

    # Catriona the studio master, at the Broughton Craft Workshop, for any skill.
    res3 = client.post("/v1/ai/flow-mastery", json={"city": "Lisbon", "skill": "Ceramics"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False

    # `salon_confirmed: True` confirmed a six-person table hosted by Ewan the philosopher
    # and sourdough baker. Nothing was booked and nobody was invited.
    res4 = client.post("/v1/ai/meaningful-salons", json={"city": "Lisbon", "theme": "Courage"})
    assert res4.status_code == 200
    assert res4.json()["confirmed"] is False
    assert len(res4.json()["table_prompts"]) == 3      # a writing prompt is not a claim

def test_proactive_butler_4_superhuman_engines(cfg):
    client = TestClient(create_app(cfg))
    # Detected a "serendipity window" with a named friend 400 m away and a weather
    # condition. There is no location sharing and no weather provider.
    res1 = client.post("/v1/ai/serendipity-engine", json={"user": "Robert"})
    assert res1.status_code == 200
    assert res1.json()["overlaps"] == []

    # Claimed to *detect* an emotional state, then matched the user with Isla, a quiet tea
    # and book enthusiast. Nothing here reads a mood.
    res2 = client.post("/v1/ai/empathy-vibe-tuner", json={"vibe": "Overstimulated"})
    assert res2.status_code == 200
    assert res2.json()["options"] == []
    assert res2.json()["no_mood_detection"]

    res3 = client.post("/v1/ai/group-concierge", json={"group": "Lisbon Crew"})
    assert res3.status_code == 200
    assert res3.json()["plans"] == []

    # Three friends with invented notes and nudges, while the reconnect module that ranks
    # real people by contact decay sat unread since Sprint 1.
    res4 = client.post("/v1/ai/friendship-compounding", json={})
    assert res4.status_code == 200
    assert res4.json()["people"] == []

def test_butler_of_true_life_value(cfg):
    client = TestClient(create_app(cfg))
    # Three more invented scores: longevity, life vision, and a "fulfilment ROI" that
    # divided money by a number the app did not have.
    res1 = client.post("/v1/ai/vitality-circadian-flow", json={})
    assert res1.status_code == 200
    assert res1.json()["wearable_connected"] is False
    assert "longevity_score" not in res1.json()

    res2 = client.post("/v1/ai/regret-minimization", json={})
    assert res2.status_code == 200
    assert "life_vision_score" not in res2.json()
    assert res2.json()["goals"] == []

    res3 = client.post("/v1/ai/wealth-value-optimizer", json={})
    assert res3.status_code == 200
    assert res3.json()["splits"] == [] and res3.json()["no_roi"]

    # It claimed to log a peak moment and stored nothing; `lifetime_gratitude_count` was a
    # constant. Reflections are real rows now, so a written one comes back in the count.
    res4 = client.post("/v1/ai/stoic-presence-mirror", json={"note": "Sunset tea"})
    assert res4.status_code == 200
    assert res4.json()["logged"] is True and res4.json()["total"] == 1

def test_zero_user_event_seeding_and_tastemaker_curation(cfg):
    client = TestClient(create_app(cfg))
    # 220 "verified events" aggregated from Resident Advisor, Luma, Dice.fm and "Local
    # Culture Substacks". The real crawler here is feed discovery, and it needs a URL.
    res1 = client.post("/v1/seeding/zero-user-event-crawler", json={"city": "Edinburgh"})
    assert res1.status_code == 400
    assert "220" not in res1.text

    # Curation needs curators: it listed "hidden gems" chosen by nobody, and gravity scores
    # for venues it had invented. All three are views over the seeded map and the board now,
    # so an unseeded city is honestly empty.
    for path in ("/v1/seeding/tastemaker-curation", "/v1/seeding/recurring-gravity-hubs",
                 "/v1/seeding/city-culture-guide"):
        res = client.post(path, json={"city": "Edinburgh"})
        assert res.status_code == 200, path
        assert res.json()["empty"] is True, path
        assert res.json()["places"] == [] and res.json()["events"] == [], path

def test_full_day_user_ux_simulation(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/simulation/full-day-ux-optimizer", json={"persona": "Digital Nomad", "city": "Edinburgh"})
    assert res.status_code == 200
    assert res.json()["simulation_complete"] is True
    assert len(res.json()["simulated_24h_timeline"]) >= 6
    assert res.json()["simulation_metrics"]["lifelong_memory_dividends"] >= 3

def test_multi_demographic_simulation_suite(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/simulation/multi-demographic-suite", json={"profile": "ALL"})
    assert res.status_code == 200
    assert res.json()["suite_simulation_complete"] is True
    assert res.json()["total_demographics_covered"] >= 6

def test_ultimate_frontier_capabilities(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/mesh/offline-peer-sync", json={})
    assert res1.status_code == 200
    assert res1.json()["mesh_active"] is True

    res2 = client.post("/v1/wearables/ambient-whispers", json={})
    assert res2.status_code == 200
    assert res2.json()["wearables_synced"] is True

    res3 = client.post("/v1/trust/web-of-trust", json={"target_user": "Elena"})
    assert res3.status_code == 200
    assert res3.json()["trust_verified"] is True

    res4 = client.post("/v1/atlas/living-memory-map", json={})
    assert res4.status_code == 200
    assert res4.json()["atlas_active"] is True

def test_global_flourishing_and_regenerative_earth(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/impact/regenerative-earth", json={"city": "Edinburgh"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/impact/zero-waste-pantry", json={"city": "Edinburgh"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/impact/compassion-listener-network", json={"city": "Lisbon"})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res4 = client.post("/v1/impact/intergenerational-guild", json={"city": "Edinburgh"})
    assert res4.status_code == 200
    assert res4.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_universal_master_controller(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/os/master-controller", json={"mode": "High Growth & Adventure", "city": "Edinburgh"})
    assert res.status_code == 200
    assert res.json()["master_controller_online"] is True
    assert "ai_butler_v4" in res.json()["orchestrated_subsystems"]
    assert res.json()["active_mode"] == "High Growth & Adventure"

def test_nextgen_content_seeding_engines(cfg):
    client = TestClient(create_app(cfg))
    # All four branched on the word "munich" in the request: say it and you got hand-written
    # Isar river swims and Krautrock nights, say anything else and you got Edinburgh's.
    for path in ("/v1/seeding/underground-vinyl-radar", "/v1/seeding/culinary-popup-drops",
                 "/v1/seeding/wild-nature-trails", "/v1/seeding/literary-salon-radar"):
        res = client.post(path, json={"city": "Edinburgh"})
        assert res.status_code == 200, path
        assert res.json()["empty"] is True, path
        for invented in ("Krautrock", "Unter Deck", "Isar", "Flaucher"):
            assert invented not in res.text, f"{path} still names {invented}"

def test_hyper_autonomous_discovery_signals(cfg):
    client = TestClient(create_app(cfg))
    # Trending venues with view counts and a virality index. Nothing counts views or shares
    # here, so the measure is the only real one: how many people said they are going.
    res1 = client.post("/v1/seeding/social-viral-pulse", json={"city": "Edinburgh"})
    assert res1.status_code == 200
    assert res1.json()["meetups"] == [] and res1.json()["no_virality_index"]

    # Live crowd density per venue, with anomaly percentages, from no sensor at all.
    res2 = client.post("/v1/seeding/live-footfall-anomalies", json={"city": "Edinburgh"})
    assert res2.status_code == 200
    assert res2.json()["available"] is False and "sensor" in res2.json()["reason"]

    # Scraping publications with no agreement to do so is somebody else's work taken
    # without asking. Subscribing to a feed they publish is the same content, offered.
    res3 = client.post("/v1/seeding/editorial-press-scraper", json={"city": "Edinburgh"})
    assert res3.status_code == 200
    assert res3.json()["available"] is False and "scrape" in res3.json()["reason"]

    # It branched on the word "munich" in the request and returned hand-written Isar
    # river-surf telemetry; everything else got Edinburgh's.
    res4 = client.post("/v1/seeding/weather-tide-triggers", json={"city": "Edinburgh"})
    assert res4.status_code == 200
    assert res4.json()["available"] is False
    assert "Isar" not in res4.text

def test_live_external_api_ingestion(cfg):
    client = TestClient(create_app(cfg))
    # This one did make a real Open-Meteo call — and then fell back to a hardcoded 22.4 C on
    # any failure, from a lat/lon table with exactly two cities in it. A failed fetch is a
    # status now, not a plausible temperature.
    res = client.post("/v1/seeding/live-external-api-ingest", json={"city": "Edinburgh"})
    assert res.status_code == 200
    assert res.json()["available"] is False
    assert "22.4" not in res.text

def test_nightlife_party_and_speakeasy_engine(cfg):
    client = TestClient(create_app(cfg))
    res1 = client.post("/v1/nightlife/party-radar", json={"city": "Munich"})
    assert res1.status_code == 200
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking
    assert res1.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res2 = client.post("/v1/nightlife/secret-speakeasies", json={"city": "Munich"})
    assert res2.status_code == 200
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking
    assert res2.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res3 = client.post("/v1/nightlife/guestlist-vip", json={"city": "Lisbon", "venue": "Blitz Club", "crew_size": 2})
    assert res3.status_code == 200
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking
    assert res3.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

    res4 = client.post("/v1/nightlife/crew-pregame", json={"destination": "Blitz Club", "city": "Munich"})
    assert res4.status_code == 200
    assert res4.json()["matched"] is False     # was a literal: invented people, sometimes an invented booking

def test_daily_reflection_synthesis(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/journal/daily-reflection-synthesis", json={"city": "Munich", "date": "Today"})
    assert res.status_code == 200
    data = res.json()
    assert data["synthesis_complete"] is True
    assert len(data["gratitude_dividends"]) >= 3
    assert data["time_capsule_status"] == "SEALED_IN_SUBSTRATE_GRAPH"
    assert "presence_score" in data["daily_vitality_metrics"]

def test_voice_copilot_and_spoken_ar(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/voice/copilot-chat", json={"query": "What vinyl clubs are open tonight?", "city": "Munich"})
    assert res.status_code == 200
    data = res.json()
    assert data["voice_response_generated"] is True
    assert "Blitz Club" in data["voice_reply_text"]
    assert "<speak>" in data["tts_ssml"]

def test_universal_markdown_export(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/export/universal-markdown", json={"format": "Obsidian"})
    assert res.status_code == 200
    data = res.json()
    assert data["export_complete"] is True
    assert data["total_vault_files"] >= 40
    assert "01_Daily_Retrospectives" in data["vault_structure"]

def test_micro_masterclasses_and_neighborhood_guilds(cfg):
    client = TestClient(create_app(cfg))
    # Three masterclasses with named tutors, for any city.
    res = client.post("/v1/workshops/micro-masterclasses",
                      json={"city": "Munich", "skill": "welding"})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is False and data["people"] == []
    assert "micro_masterclasses" not in data

def test_smart_layover_and_stopover_navigator(cfg):
    client = TestClient(create_app(cfg))
    res = client.post("/v1/travel/layover-discovery", json={"hub": "Munich Airport (MUC)", "layover_hours": 4.5})
    assert res.status_code == 200
    data = res.json()
    assert data["layover_navigator_active"] is True
    assert "Eisbachwelle" in str(data["curated_micro_escape"])
    assert "Armed" in data["gate_return_alarm"]
