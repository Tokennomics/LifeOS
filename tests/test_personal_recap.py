"""The personal surfaces have to be about the person.

All three of these were props. A brand-new account was told it had 12 real-world meetups,
34 kudos, 48.5 focus hours and a "Crag Pioneer" badge in Lisbon — and two different accounts
got byte-identical statistics, because the numbers were literals in the handler.

That is worse than not having the feature. A statistic about *me* that is obviously not about
me doesn't read as a placeholder, it reads as the whole app being fake, and it costs the
parts that genuinely work. So the tests here are mostly one assertion in different clothes:
**the number came from what this account actually did.**
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.personal import recap

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def two(cfg):
    client = TestClient(create_app(cfg))
    heads = {}
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        heads[name] = {"Authorization": f"Bearer {token}"}
    return client, heads


PERSONAL = ["/v1/wrapped/monthly", "/v1/gamification/passport",
            "/v1/vitals/social-battery"]


# ---- the finding -----------------------------------------------------------------

@pytest.mark.parametrize("path", PERSONAL)
def test_a_brand_new_account_is_not_told_it_has_a_history(two, path):
    """The exact thing that was happening: an empty graph reporting a full month."""
    client, heads = two
    body = client.get(path, headers=heads["ana"]).json()
    numbers = [v for v in body.values() if isinstance(v, (int, float))
               and not isinstance(v, bool)]
    assert all(n in (0, 14, 30) for n in numbers), \
        f"{path} invented a figure for an empty account: {body}"


def test_two_accounts_do_not_share_a_history(two):
    """They returned byte-identical 'personal' data, because it was a literal."""
    client, heads = two
    client.post("/v1/capture", headers=heads["ana"], json={"text": "Climbed at Monsanto"})

    mine = client.get("/v1/wrapped/monthly", headers=heads["ana"]).json()
    theirs = client.get("/v1/wrapped/monthly", headers=heads["bruno"]).json()
    assert mine["captures"] == 1 and theirs["captures"] == 0


def test_the_real_implementation_is_not_shadowed(two):
    """There were two `/wrapped/monthly` handlers. FastAPI matches the first registered, so
    the graph-backed one further down the file had never run once."""
    client, heads = two
    body = client.get("/v1/wrapped/monthly", headers=heads["ana"]).json()
    assert "focus_hours" not in body, "the prop is still winning the route"
    assert body["window_days"] == 30 and body["empty"] is True


def test_no_route_is_defined_twice():
    """The shadowing above is invisible in review and silent at runtime — the second
    definition simply never runs."""
    import collections
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "gateway" / "modules_api.py").read_text(encoding="utf-8")
    routes = re.findall(r'\n    @router\.(get|post|put|delete|patch)\("([^"]+)"\)', src)
    duplicates = {r: n for r, n in collections.Counter(routes).items() if n > 1}
    assert duplicates == {}, f"these routes are defined more than once: {duplicates}"


# ---- an empty month says so ------------------------------------------------------

def test_an_empty_month_says_what_would_fill_it(two):
    client, heads = two
    body = client.get("/v1/wrapped/monthly", headers=heads["ana"]).json()
    assert body["empty"] is True
    assert body["days_shown_up"] == 0 and body["tasks_done"] == 0
    assert "capture" in body["note"].lower()


def test_an_empty_month_is_not_offered_for_sharing(two):
    """Handing somebody a share button for a month in which they did nothing is the app
    asking them to advertise its own emptiness."""
    client, heads = two
    assert client.get("/v1/wrapped/monthly", headers=heads["ana"]).json()["share_text"] == ""


def test_a_month_with_something_in_it_counts_it(two):
    client, heads = two
    for text in ("Coffee with Rui", "Climbing Saturday", "Book the flight"):
        client.post("/v1/capture", headers=heads["ana"], json={"text": text})

    body = client.get("/v1/wrapped/monthly", headers=heads["ana"]).json()
    assert body["captures"] == 3
    assert body["days_shown_up"] == 1, "three notes on one day is one day shown up"
    assert body["empty"] is False and body["share_text"]


def test_days_shown_up_is_counted_not_estimated(graph):
    """It used to be `tasks_done + 3` — a real number with three added to it, which is the
    quietly dishonest kind: it moves when you do and is still wrong."""
    session = graph.session("t", {"content:write", "content:read"})
    session.create_entity("content", {"type": "capture", "text": "one"}, source="t")
    assert recap.monthly(graph)["days_shown_up"] == 1


def test_old_activity_falls_out_of_the_window(graph):
    session = graph.session("t", {"content:write", "content:read"})
    session.create_entity("content", {"type": "capture", "text": "ages ago"}, source="t",
                          created_at="2024-01-05T10:00:00+00:00")
    assert recap.monthly(graph)["captures"] == 0
    assert recap.monthly(graph, now="2024-01-10T10:00:00+00:00")["captures"] == 1


# ---- the passport ----------------------------------------------------------------

def test_the_passport_starts_empty_and_says_how_to_fill_it(two):
    client, heads = two
    body = client.get("/v1/gamification/passport", headers=heads["ana"]).json()
    assert body["stamps"] == [] and body["stamps_count"] == 0
    assert body["empty"] is True and "attended" in body["note"].lower()


def test_a_stamp_is_somewhere_you_actually_went(graph):
    session = graph.session("t", {"events:write", "events:read"})
    session.create_entity("event", {"type": "social", "title": "Bouldering",
                                    "place": "Monsanto", "city": "Lisbon",
                                    "status": "attended", "topic": "climbing",
                                    "start": "2026-08-02T18:00:00+00:00"}, source="t")
    session.create_entity("event", {"type": "social", "title": "Maybe later",
                                    "place": "Somewhere", "city": "Lisbon",
                                    "status": "invited"}, source="t")

    body = recap.passport(graph)
    assert body["stamps_count"] == 1
    assert body["stamps"][0]["venue"] == "Monsanto"
    assert body["cities"] == ["Lisbon"]


def test_the_passport_can_be_asked_for_one_city(graph):
    session = graph.session("t", {"events:write", "events:read"})
    for city, place in (("Lisbon", "Monsanto"), ("Porto", "Foz")):
        session.create_entity("event", {"type": "social", "place": place, "city": city,
                                        "status": "attended"}, source="t")
    assert [s["venue"] for s in recap.passport(graph, "Porto")["stamps"]] == ["Foz"]
    assert recap.passport(graph)["stamps_count"] == 2


# ---- the social battery ----------------------------------------------------------

def test_with_nothing_logged_the_battery_says_it_does_not_know(two):
    """Better than picking a cheerful percentage. It was 82% for everybody, forever."""
    client, heads = two
    body = client.get("/v1/vitals/social-battery", headers=heads["ana"]).json()
    assert body["state"] == "unknown"
    assert body["recent_outings"] == 0
    assert "battery_pct" not in body


def test_the_battery_reflects_what_you_actually_did(graph):
    session = graph.session("t", {"events:write", "events:read"})
    recent = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=2)).isoformat()
    for i in range(5):
        session.create_entity("event", {"type": "social", "status": "attended",
                                        "start": recent, "place": f"Place {i}"}, source="t")

    body = recap.social_battery(graph)
    assert body["state"] == "full" and body["recent_outings"] == 5
    assert "5 outings" in body["recommendation"]


def test_a_quiet_fortnight_reads_as_steady_not_as_failure(graph):
    session = graph.session("t", {"events:write", "events:read"})
    session.create_entity("event", {"type": "social", "status": "attended", "place": "Bar",
                                    "start": (datetime.datetime.now(datetime.timezone.utc)
                                              - datetime.timedelta(days=3)).isoformat()},
                          source="t")
    assert recap.social_battery(graph)["state"] == "steady"


def test_the_battery_reports_no_precision_it_does_not_have(graph):
    """A percentage from three data points is a made-up number with a decimal point."""
    session = graph.session("t", {"events:write", "events:read"})
    session.create_entity("event", {"type": "social", "status": "attended", "place": "Bar",
                                    "start": datetime.datetime.now(
                                        datetime.timezone.utc).isoformat()}, source="t")
    body = recap.social_battery(graph)
    assert set(body) == {"state", "recent_outings", "upcoming_outings", "window_days",
                         "recommendation"}
    assert body["state"] in ("quiet", "steady", "full")


# ---- streaks, heatmap, standing --------------------------------------------------

def _mark_days(graph, offsets):
    """Activity on each of these days-ago."""
    session = graph.session("t", {"content:write", "content:read"})
    now = datetime.datetime.now(datetime.timezone.utc)
    for offset in offsets:
        session.create_entity("content", {"type": "capture", "text": f"day -{offset}"},
                              source="t",
                              created_at=(now - datetime.timedelta(days=offset)).isoformat())


def test_a_fresh_account_has_no_streak(two):
    client, heads = two
    body = client.get("/v1/gamification/streaks", headers=heads["ana"]).json()
    assert body["current_streak_days"] == 0 and body["empty"] is True
    assert "capture" in body["note"].lower()


def test_a_streak_is_consecutive_days_you_showed_up(graph):
    _mark_days(graph, [0, 1, 2])
    body = recap.streaks(graph)
    assert body["current_streak_days"] == 3 and body["longest_streak_days"] == 3


def test_a_gap_breaks_the_streak_but_not_the_record(graph):
    _mark_days(graph, [0, 1, 5, 6, 7, 8])
    body = recap.streaks(graph)
    assert body["current_streak_days"] == 2
    assert body["longest_streak_days"] == 4


def test_todays_silence_does_not_end_yesterdays_streak(graph):
    """A streak that resets at midnight punishes you for sleeping."""
    _mark_days(graph, [1, 2, 3])
    assert recap.streaks(graph)["current_streak_days"] == 3


def test_the_heatmap_is_your_own_activity(graph):
    """Was `(i % 3) + 1` — a sawtooth that looks like data from a distance and is identical
    for every account. It even imported `random` and never used it."""
    body = recap.heatmap(graph)
    assert len(body["days"]) == 30
    assert body["active_days"] == 0 and body["empty"] is True
    assert {d["level"] for d in body["days"]} == {0}

    _mark_days(graph, [0, 3])
    after = recap.heatmap(graph)
    assert after["active_days"] == 2 and after["empty"] is False


def test_the_heatmap_is_not_the_same_shape_for_everyone(two):
    client, heads = two
    client.post("/v1/capture", headers=heads["ana"], json={"text": "something"})
    mine = client.get("/v1/routines/heatmap", headers=heads["ana"]).json()
    theirs = client.get("/v1/routines/heatmap", headers=heads["bruno"]).json()
    assert mine["active_days"] == 1 and theirs["active_days"] == 0


def test_an_outing_counts_for_more_than_a_note(graph):
    """Leaving the house is the thing this app is for."""
    session = graph.session("t", {"events:write", "events:read"})
    session.create_entity("event", {"type": "social", "status": "attended", "place": "Crag",
                                    "start": datetime.datetime.now(
                                        datetime.timezone.utc).isoformat()}, source="t")
    today = [d for d in recap.heatmap(graph)["days"] if d["level"] > 0]
    assert today and today[0]["level"] >= 1


def test_standing_reports_what_you_did_not_a_score_out_of_100(two):
    """Was 98/100 "LEGEND_CREW_MEMBER", 99% punctual arrivals and a 4.98 crew rating — for
    every account, including one made ten seconds ago. Nobody rates anybody in this app, so
    the score could only ever have been invented."""
    client, heads = two
    body = client.get("/v1/trust/karma-score", headers=heads["ana"]).json()
    assert "karma_score" not in body and "trust_tier" not in body
    assert body["outings_attended"] == 0 and body["empty"] is True
    assert "nothing logged" in body["summary"].lower()


def test_standing_counts_real_outings(graph):
    session = graph.session("t", {"events:write", "events:read"})
    for place in ("Crag", "Cafe"):
        session.create_entity("event", {"type": "social", "status": "attended",
                                        "place": place,
                                        "start": datetime.datetime.now(
                                            datetime.timezone.utc).isoformat()}, source="t")
    body = recap.standing(graph)
    assert body["outings_attended"] == 2 and body["empty"] is False
    assert "2 outings" in body["summary"]


def test_the_three_time_surfaces_agree_with_each_other(graph):
    """Heatmap, streak and recap read the same days through one helper, so they cannot tell
    you three different stories about the same fortnight."""
    _mark_days(graph, [0, 1, 2])
    assert recap.streaks(graph)["current_streak_days"] == 3
    assert recap.heatmap(graph)["active_days"] == 3
    assert recap.monthly(graph)["days_shown_up"] == 3


# ---- what was removed stays removed ----------------------------------------------

def test_the_fake_age_check_is_gone(two):
    """`/v1/zk/verify-attribute` returned verified=True with a random "ZK-" string for any
    attribute from any caller — including AGE_OVER_18, in a repo containing a dating
    surface. An age check that passes everyone is worse than none, because the user reading
    "Proof Verified" believes it happened."""
    client, heads = two
    assert client.post("/v1/zk/verify-attribute", headers=heads["ana"],
                       json={"attribute": "AGE_OVER_18"}).status_code == 404


def test_the_pwa_no_longer_offers_to_prove_your_age():
    import pathlib
    app_js = (pathlib.Path(__file__).resolve().parent.parent
              / "surfaces" / "app" / "www" / "app.js").read_text(encoding="utf-8")
    # Match live markup, not prose — the comment explaining why the card is gone naturally
    # quotes what it used to say.
    assert "data-act=\"zk-verify-attr\"" not in app_js
    assert "zk-proof-output" not in app_js
    assert "/v1/zk/verify-attribute" not in app_js


def test_the_invented_leaderboard_is_gone(two):
    client, heads = two
    assert client.get("/v1/gamification/leaderboard",
                      headers=heads["ana"]).status_code == 404
