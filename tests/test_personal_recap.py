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
