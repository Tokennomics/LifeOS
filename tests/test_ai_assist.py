"""The `/ai/*` surface, which never called a model.

Twenty endpoints returned prose. The tests that mattered were never written, so these are
about the two properties that keep it from sliding back:

1. **Nothing is invented.** Every suggestion has to trace to a record somebody created. The
   sharpest form of that is the empty case: a fresh account in an empty city gets nothing,
   because nothing is there. That is the assertion the old implementation failed twenty
   times over.
2. **No key is not a broken app.** Without `ANTHROPIC_API_KEY` these still answer, from the
   graph, with `assisted: false`. The two that genuinely cannot work without one say so
   instead of shrinking the lie.

There is also a fake Claude here, because the real one must never be called from a test —
and because "the model was asked, and its answer was used" is itself a claim worth pinning.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.ai import assist, reflect

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


class FakeClaude:
    """Available, deterministic, and records what it was asked — so a test can check that
    the model was given facts rather than a bare instruction."""

    def __init__(self, text="one\ntwo\nthree", payload=None, explode=False):
        self.available = True
        self.text, self.payload, self.explode = text, payload or {}, explode
        self.prompts = []

    def complete(self, system, user, **kw):
        self.prompts.append((system, user))
        if self.explode:
            raise RuntimeError("model unavailable")
        return self.text

    def complete_json(self, system, user, **kw):
        self.prompts.append((system, user))
        if self.explode:
            raise RuntimeError("model unavailable")
        return self.payload


@pytest.fixture
def city(cfg):
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


def _soon(hours=5):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=hours)).isoformat()


# ---- the empty case, twenty times over --------------------------------------

def test_an_empty_city_has_no_itinerary(city):
    """Fabrica, Miradouro and Lux Frágil were returned to every user in every city."""
    client, people = city
    body = client.post("/v1/ai/micro-itinerary", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["stops"] == [] and body["empty"] is True


def test_the_empty_itinerary_says_what_would_fix_it(city):
    client, people = city
    body = client.post("/v1/ai/micro-itinerary", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert "Propose one thing" in body["suggestion"]


def test_an_empty_crew_has_no_plan(city):
    client, people = city
    body = client.post("/v1/ai/squad-agent", json={"crew_id": "c1"},
                       headers=people["ana"]["h"]).json()
    assert body["plans"] == []


def test_the_crew_plan_states_what_it_does_not_do(city):
    """It reported a negotiation across five calendars, a confirmed table and an
    auto-split. None of those systems exist, so saying nothing would still mislead."""
    client, people = city
    body = client.post("/v1/ai/squad-agent", json={}, headers=people["ana"]["h"]).json()
    assert set(body["not_included"]) == {"calendar negotiation", "venue booking", "payment"}


# ---- real records come back --------------------------------------------------

def test_a_real_meetup_appears_in_the_itinerary(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Bouldering at Monsanto",
                      "starts_at": _soon(), "place": "Monsanto"},
                headers=people["bruno"]["h"])
    body = client.post("/v1/ai/micro-itinerary", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert [s["what"] for s in body["stops"]] == ["Bouldering at Monsanto"]
    assert body["stops"][0]["kind"] == "meetup"


def test_every_stop_carries_the_record_it_came_from(city):
    """The claim is that nothing is invented, and a reference is how that stays checkable."""
    client, people = city
    made = client.post("/v1/city/meetups",
                       json={"city": "Lisbon", "title": "Ramen", "starts_at": _soon()},
                       headers=people["bruno"]["h"]).json()
    body = client.post("/v1/ai/micro-itinerary", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["stops"][0]["ref"] == made["meetup_id"]


def test_something_next_month_is_not_tonight(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Far off", "starts_at": _soon(24 * 20)},
                headers=people["bruno"]["h"])
    body = client.post("/v1/ai/micro-itinerary", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["stops"] == []


def test_quests_are_the_same_real_records(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Sunset walk", "starts_at": _soon()},
                headers=people["bruno"]["h"])
    body = client.post("/v1/ai/spontaneous-quests", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert [q["title"] for q in body["quests"]] == ["Sunset walk"]


def test_the_city_is_remembered_from_your_arrival(city):
    client, people = city
    client.post("/v1/city/around", json={"city": "Lisbon"}, headers=people["ana"]["h"])
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Ramen", "starts_at": _soon()},
                headers=people["bruno"]["h"])
    body = client.post("/v1/ai/micro-itinerary", json={}, headers=people["ana"]["h"]).json()
    assert body["city"] == "lisbon" and len(body["stops"]) == 1


# ---- icebreakers -------------------------------------------------------------

def test_no_match_means_no_opener(city):
    """It wrote three lines about a washed Ethiopian pour-over for any name at all,
    including one typed by hand into the request."""
    client, people = city
    body = client.post("/v1/ai/copilot-icebreaker",
                       json={"target_account_id": people["bruno"]["id"], "city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["openers"] == []
    assert "publish what you are up for" in body["suggestion"]


def test_an_opener_is_built_from_what_you_both_published(city):
    client, people = city
    for who in ("ana", "bruno"):
        client.post("/v1/synergy/open-to",
                    json={"city": "Lisbon", "activity": "bouldering"},
                    headers=people[who]["h"])
    body = client.post("/v1/ai/copilot-icebreaker",
                       json={"target_account_id": people["bruno"]["id"], "city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["openers"]
    assert all("bouldering" in o or "bruno" in o for o in body["openers"])
    assert body["grounded_in"] == ["you both published: bouldering", "city: Lisbon"]


def test_an_opener_never_names_a_venue_nobody_mentioned(city):
    client, people = city
    for who in ("ana", "bruno"):
        client.post("/v1/synergy/open-to",
                    json={"city": "Lisbon", "activity": "bouldering"},
                    headers=people[who]["h"])
    body = client.post("/v1/ai/copilot-icebreaker",
                       json={"target_account_id": people["bruno"]["id"], "city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    text = " ".join(body["openers"])
    for invented in ("Fabrica", "Monsanto", "Miradouro", "Ethiopian"):
        assert invented not in text


def test_their_own_note_is_used_verbatim_when_they_wrote_one(graph):
    from modules.city import synergy
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="a", handle="ana")
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="b", handle="bruno",
                    note="crag at six")
    out = assist.icebreakers(graph, account_id="a", target_account_id="b", city="Lisbon")
    assert any("crag at six" in o for o in out["openers"])


# ---- with and without a key --------------------------------------------------

def test_without_a_key_it_still_answers(city):
    client, people = city
    body = client.post("/v1/ai/micro-itinerary", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert body["assisted"] is False
    assert "ANTHROPIC_API_KEY" in body["reason"]


def test_with_a_key_the_model_writes_the_openers(graph):
    from modules.city import synergy
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="a", handle="ana")
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="b", handle="bruno")
    fake = FakeClaude("Fancy a climb later?\nSame plan as me.\nFree at six?")
    out = assist.icebreakers(graph, account_id="a", target_account_id="b", city="Lisbon",
                             claude=fake)
    assert out["assisted"] is True
    assert out["openers"] == ["Fancy a climb later?", "Same plan as me.", "Free at six?"]


def test_the_model_is_given_the_facts_not_just_an_instruction(graph):
    """Grounding is the whole design. A model asked to write an icebreaker with no facts
    writes plausible venue names, which is the original bug with a bigger bill."""
    from modules.city import synergy
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="a", handle="ana")
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="b", handle="bruno")
    fake = FakeClaude()
    assist.icebreakers(graph, account_id="a", target_account_id="b", city="Lisbon",
                       claude=fake)
    _, user = fake.prompts[0]
    assert "bouldering" in user


def test_a_model_failure_falls_back_rather_than_500ing(graph):
    from modules.city import synergy
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="a", handle="ana")
    synergy.open_to(graph, "Lisbon", "bouldering", account_id="b", handle="bruno")
    out = assist.icebreakers(graph, account_id="a", target_account_id="b", city="Lisbon",
                             claude=FakeClaude(explode=True))
    assert out["assisted"] is False
    assert out["openers"]


# ---- the two that genuinely need a key --------------------------------------

def test_translation_is_unavailable_without_a_key():
    out = assist.translate("it's a wee bit dreich", "Edinburgh")
    assert out["available"] is False
    assert "braw" not in str(out)


def test_translation_works_with_a_key():
    fake = FakeClaude(payload={"translation": "it is a bit grey", "etiquette": "",
                               "glossary": {"dreich": "grey and damp"}})
    out = assist.translate("it's a wee bit dreich", "Edinburgh", claude=fake)
    assert out["available"] is True
    assert out["translation"] == "it is a bit grey"


def test_translation_needs_a_phrase():
    with pytest.raises(ValueError):
        assist.translate("", "Edinburgh")


def test_the_voice_brief_does_not_claim_to_hear_anything():
    out = assist.extract_plan("coffee at four then drinks")
    assert out["speech_to_text"] is False
    assert out["available"] is False


def test_the_voice_brief_reads_a_transcript_with_a_key():
    fake = FakeClaude(payload={"stops": [{"when": "16:00", "place": "the square",
                                          "what": "coffee"}]})
    out = assist.extract_plan("coffee at four in the square", claude=fake)
    assert out["stops"][0]["what"] == "coffee"
    assert out["created"] is False       # reading a note does not create a meetup


def test_the_voice_brief_needs_text():
    with pytest.raises(ValueError):
        assist.extract_plan("")


# ---- reflections are real rows ----------------------------------------------

def test_a_reflection_is_stored_and_counted(graph):
    """`lifetime_gratitude_count` was a constant and nothing was ever written."""
    assert reflect.count(graph) == 0
    out = reflect.log(graph, "the light on the bridge")
    assert out["logged"] is True and out["total"] == 1
    assert reflect.entries(graph)[0]["note"] == "the light on the bridge"


def test_an_empty_reflection_is_refused(graph):
    with pytest.raises(reflect.ReflectError):
        reflect.log(graph, "   ")


def test_reading_without_writing_returns_the_history(city):
    client, people = city
    client.post("/v1/ai/stoic-presence-mirror", json={"note": "first"},
                headers=people["ana"]["h"])
    body = client.post("/v1/ai/stoic-presence-mirror", json={},
                       headers=people["ana"]["h"]).json()
    assert body["logged"] is False and body["total"] == 1


def test_reflections_are_not_shared_between_accounts(city):
    """They live in the author's own slice. Nobody else has any business reading them."""
    client, people = city
    client.post("/v1/ai/stoic-presence-mirror", json={"note": "mine"},
                headers=people["ana"]["h"])
    body = client.post("/v1/ai/stoic-presence-mirror", json={},
                       headers=people["bruno"]["h"]).json()
    assert body["total"] == 0
    assert body["recent"] == []


# ---- no scores ---------------------------------------------------------------

def test_purpose_has_no_score(graph):
    out = reflect.purpose(graph)
    for invented in ("fulfillment_score", "life_vision_score", "longevity_score",
                     "fulfillment_roi_metric"):
        assert invented not in out
    assert out["no_score"]


def test_purpose_reports_emptiness_rather_than_a_cheerful_number(graph):
    assert reflect.purpose(graph)["empty"] is True


def test_purpose_picks_up_a_reflection(graph):
    reflect.log(graph, "something")
    out = reflect.purpose(graph)
    assert out["empty"] is False and out["reflection_count"] == 1


def test_spending_reports_no_roi(city):
    client, people = city
    body = client.post("/v1/ai/wealth-value-optimizer",
                       headers=people["ana"]["h"]).json()
    assert body["no_roi"] and body["splits"] == []
    assert "fulfillment_roi_metric" not in body


def test_the_vitality_endpoint_does_not_invent_a_wearable(city):
    client, people = city
    body = client.post("/v1/ai/vitality-circadian-flow",
                       headers=people["ana"]["h"]).json()
    assert body["wearable_connected"] is False
    assert "longevity_score" not in body


# ---- the smaller ones --------------------------------------------------------

def test_quiet_options_filter_by_group_size(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Quiet tea", "starts_at": _soon()},
                headers=people["bruno"]["h"])
    body = client.post("/v1/ai/empathy-vibe-tuner",
                       json={"city": "Lisbon", "max_group": 4},
                       headers=people["ana"]["h"]).json()
    assert [o["title"] for o in body["options"]] == ["Quiet tea"]


def test_a_bigger_plan_is_not_offered_as_a_quiet_one(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Big night", "starts_at": _soon()},
                headers=people["bruno"]["h"])
    body = client.post("/v1/ai/empathy-vibe-tuner",
                       json={"city": "Lisbon", "max_group": 0},
                       headers=people["ana"]["h"]).json()
    assert body["options"] == []


def test_nothing_reads_your_mood(city):
    client, people = city
    body = client.post("/v1/ai/empathy-vibe-tuner", json={"city": "Lisbon"},
                       headers=people["ana"]["h"]).json()
    assert "detected_state" not in body
    assert body["no_mood_detection"]


def test_autorsvp_matches_but_never_joins(city):
    client, people = city
    client.post("/v1/city/meetups",
                json={"city": "Lisbon", "title": "Dawn patrol surf", "starts_at": _soon()},
                headers=people["bruno"]["h"])
    client.post("/v1/city/around", json={"city": "Lisbon"}, headers=people["ana"]["h"])
    body = client.post("/v1/ai/smart-autorsvp", json={"rule": "surf"},
                       headers=people["ana"]["h"]).json()
    assert [m["title"] for m in body["matches"]] == ["Dawn patrol surf"]
    assert body["auto_joined"] is False
    assert body["matches"][0]["you_are_going"] is False


def test_reconnect_lists_only_people_you_added(city):
    client, people = city
    body = client.post("/v1/ai/friendship-compounding", json={},
                       headers=people["ana"]["h"]).json()
    assert body["people"] == []
    client.post("/v1/people", json={"name": "Kim"}, headers=people["ana"]["h"])
    after = client.post("/v1/ai/friendship-compounding", json={},
                        headers=people["ana"]["h"]).json()
    assert [p["name"] for p in after["people"]] == ["Kim"]


def test_serendipity_is_the_overlap_the_app_can_observe(city):
    client, people = city
    for who in ("ana", "bruno"):
        client.post("/v1/synergy/open-to", json={"city": "Lisbon", "activity": "coffee"},
                    headers=people[who]["h"])
    body = client.post("/v1/ai/serendipity-engine", json={},
                       headers=people["ana"]["h"]).json()
    assert body["overlaps"][0]["people"][0]["handle"] == "bruno"


def test_serendipity_invents_no_distance_or_weather(city):
    client, people = city
    body = client.post("/v1/ai/serendipity-engine", json={},
                       headers=people["ana"]["h"]).json()
    assert "weather_condition" not in body and "nearby_friend" not in body


def test_the_butler_no_longer_branches_on_keywords_in_the_request(city):
    """Saying "fringe" returned a five-stop Edinburgh week; saying "munich" returned a
    different hand-written day. Three itineraries behind a substring check."""
    client, people = city
    body = client.post("/v1/ai/outing-butler",
                       json={"weekend": "Edinburgh Fringe and the Military Tattoo"},
                       headers=people["ana"]["h"]).json()
    assert body["stops"] == []
    assert "Kirsty" not in str(body) and "Hamish" not in str(body)
