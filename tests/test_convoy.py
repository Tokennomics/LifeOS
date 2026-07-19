import datetime

import pytest

from modules.convoy import concierge, events_ingest, match_v1
from modules.memento import capsules, quests
from modules.reconnect import decay


def _future(hours=48):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)).isoformat()


def test_add_and_upcoming(graph):
    events_ingest.add_social_event(graph, "Bouldering", _future(), place="The Wall")
    with pytest.raises(ValueError):
        events_ingest.add_social_event(graph, "Bad", "not-a-date")
    upcoming = events_ingest.upcoming(graph)
    assert len(upcoming) == 1
    assert upcoming[0]["attrs"]["title"] == "Bouldering"


def test_upcoming_handles_naive_datetime_local_input(graph):
    # the app's <input type="datetime-local"> sends no timezone — must not 500
    naive = (datetime.datetime.now() + datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    events_ingest.add_social_event(graph, "Naive gig", naive)
    assert [e["attrs"]["title"] for e in events_ingest.upcoming(graph)] == ["Naive gig"]


def test_invite_rsvp_attended_compounds_into_reconnect(graph):
    event_id = events_ingest.add_social_event(graph, "Gig", _future())
    sam = decay.add_person(graph, "Sam")
    alex = decay.add_person(graph, "Alex")
    # make Sam stale so the attendance visibly refreshes them
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=50)).isoformat()
    graph.session("reconnect", decay.SCOPES).update_entity(sam, {"last_contact": past}, source="test")

    inv = match_v1.invite(graph, event_id, [sam, alex])
    assert inv["invited"] == 2
    assert "Gig" in inv["text"]

    match_v1.rsvp(graph, event_id, sam, going=True)
    match_v1.rsvp(graph, event_id, alex, going=False)
    match_v1.rsvp(graph, event_id, alex, going=True)  # changed their mind

    seen = []
    graph.bus.subscribe("event.attended", lambda t, p: seen.append(p))
    result = match_v1.attended(graph, event_id)
    assert result["people_touched"] == 2
    assert seen[0]["module"] == "convoy"
    assert decay.ranked(graph)[0]["days_since"] < 1  # Sam refreshed by Convoy — cross-module

    digest = concierge.digest(graph)
    assert "No social events" in digest["text"]  # attended events leave the digest


def test_attended_event_spawns_memento_quest(graph):
    event_id = events_ingest.add_social_event(graph, "Gallery night", _future())
    match_v1.attended(graph, event_id)
    suggestions = quests.suggestions(graph)
    assert suggestions[0]["event_id"] == event_id
    capsules.drop(graph, "that blue room", -27.47, 153.02, "GOMA", event_id=event_id)
    assert quests.suggestions(graph) == []  # quest completed


def test_digest_lists_confirmed_names(graph):
    event_id = events_ingest.add_social_event(graph, "Dinner", _future(), place="Ping Pong")
    sam = decay.add_person(graph, "Sam")
    match_v1.invite(graph, event_id, [sam])
    match_v1.rsvp(graph, event_id, sam, going=True)
    text = concierge.digest(graph)["text"]
    assert "Dinner" in text
    assert "Sam" in text
