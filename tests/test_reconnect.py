import datetime

from modules.reconnect import decay, invite


def _age(graph, person_id, days):
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    graph.session("reconnect", decay.SCOPES).update_entity(person_id, {"last_contact": past}, source="test")


def test_add_person_dedupes_by_name(graph):
    a = decay.add_person(graph, "Sam")
    b = decay.add_person(graph, "Sam")
    assert a == b


def test_ranked_orders_by_overdue(graph):
    fresh = decay.add_person(graph, "Fresh")
    stale = decay.add_person(graph, "Stale")
    _age(graph, stale, 45)  # cadence 30 -> overdue 1.5
    ranked = decay.ranked(graph)
    assert [p["name"] for p in ranked] == ["Stale", "Fresh"]
    assert ranked[0]["overdue"] >= 1.0
    assert fresh  # fresh person present with ~0 overdue
    assert ranked[1]["overdue"] < 0.1


def test_touch_bumps_contact_and_logs_event(graph):
    pid = decay.add_person(graph, "Sam")
    _age(graph, pid, 60)
    seen = []
    graph.bus.subscribe("event.attended", lambda t, p: seen.append(p))
    result = decay.touch(graph, pid)
    assert result["person"] == "Sam"
    assert seen[0]["person_id"] == pid
    assert decay.ranked(graph)[0]["days_since"] < 1
    session = graph.session("reconnect", decay.SCOPES)
    linked = session.neighbors(result["event_id"], rel="with", direction="out")
    assert linked[0]["id"] == pid


def test_invite_draft_offline(graph):
    pid = decay.add_person(graph, "Alex")
    draft = invite.draft(graph, pid)
    assert draft["method"] == "offline"
    assert "Alex" in draft["text"]
