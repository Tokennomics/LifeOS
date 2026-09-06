"""Crew polls, beacons and the plus-one pass.

Three props, each broken in a different way. `/crews/polls/vote` took any string as an
option, defaulted it to "Bouldering & Drinks" when the caller sent nothing, and stored
nothing — there was no poll. `/crews/beacon` returned `broadcasted: True` for an activity it
invented, and broadcast it to nobody. `/crews/{id}/guest-pass` returned a token derived from
the crew id — `plus_one_<crew_id>` — so anybody who saw a crew id could write a pass for it,
except that the token granted nothing because it was stored nowhere.

The assertions that matter most: nothing claims delivery, a non-member sees nothing, and a
vote can only be for an option the poll actually offers.
"""

import pytest

from gateway import accounts
from modules.crews import beacons, crews, polls

PW = "correct-horse-battery"
QUESTION = "where are we going Thursday?"
OPTIONS = ["bouldering", "dinner", "the cinema"]


@pytest.fixture
def people(graph):
    """Three accounts. `stranger` is in no crew and stays that way."""
    return {name: accounts.register(graph, name, PW)["account_id"]
            for name in ("ana", "bo", "cy", "stranger")}


@pytest.fixture
def crew(graph, people):
    """A private crew: ana administers it, bo and cy are members."""
    crew_id = crews.create(graph, "the regulars", visibility="private",
                           admin_id=people["ana"])["id"]
    for name in ("bo", "cy"):
        crews.invite(graph, crew_id, people[name], by=people["ana"])
        crews.accept_invite(graph, crew_id, people[name])
    return crew_id


# ---- polls -------------------------------------------------------------------

def test_a_poll_is_a_real_object_with_real_votes(graph, crew, people):
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"], handle="ana")
    polls.vote(graph, poll_id=opened["poll_id"], option="dinner",
               account_id=people["bo"], handle="bo")
    out = polls.vote(graph, poll_id=opened["poll_id"], option=1,
                     account_id=people["cy"], handle="cy")
    assert out["total_votes"] == 2
    assert out["leading"] == ["dinner"]
    assert sorted(out["tally"][1]["voters"]) == ["bo", "cy"]


def test_you_cannot_vote_for_something_the_poll_does_not_offer(graph, crew, people):
    """The prop echoed any string back as the answer."""
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"])
    for bad in ("Bouldering & Drinks", "", 9, -1, None):
        with pytest.raises(polls.PollError):
            polls.vote(graph, poll_id=opened["poll_id"], option=bad, account_id=people["bo"])
    assert polls.results(graph, poll_id=opened["poll_id"],
                         account_id=people["ana"])["total_votes"] == 0


def test_one_vote_each_and_changing_it_replaces_it(graph, crew, people):
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"])
    polls.vote(graph, poll_id=opened["poll_id"], option="dinner", account_id=people["bo"])
    out = polls.vote(graph, poll_id=opened["poll_id"], option="bouldering",
                     account_id=people["bo"])
    assert out["total_votes"] == 1
    assert out["tally"][0]["votes"] == 1 and out["tally"][1]["votes"] == 0
    assert out["your_vote"] == 0


def test_a_tie_is_reported_as_a_tie(graph, crew, people):
    """Picking one of them to call the winner is how a poll starts lying about what the
    crew said."""
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"])
    polls.vote(graph, poll_id=opened["poll_id"], option=0, account_id=people["bo"])
    polls.vote(graph, poll_id=opened["poll_id"], option=1, account_id=people["cy"])
    out = polls.results(graph, poll_id=opened["poll_id"], account_id=people["ana"])
    assert out["tied"] is True
    assert sorted(out["leading"]) == ["bouldering", "dinner"]


def test_a_non_member_can_neither_see_nor_vote(graph, crew, people):
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"])
    for call in (lambda: polls.results(graph, poll_id=opened["poll_id"],
                                       account_id=people["stranger"]),
                 lambda: polls.vote(graph, poll_id=opened["poll_id"], option=0,
                                    account_id=people["stranger"]),
                 lambda: polls.for_crew(graph, crew_id=crew, account_id=people["stranger"])):
        with pytest.raises(polls.PollError, match="no such poll"):
            call()


def test_the_refusal_does_not_reveal_that_the_poll_exists(graph, crew, people):
    """Same message for "not a member" and "no such thing", so a poll id cannot be used to
    probe which crews somebody is in."""
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"])
    with pytest.raises(polls.PollError) as missing:
        polls.results(graph, poll_id="not-an-id", account_id=people["stranger"])
    with pytest.raises(polls.PollError) as blocked:
        polls.results(graph, poll_id=opened["poll_id"], account_id=people["stranger"])
    assert str(missing.value) == str(blocked.value)


def test_a_blocked_member_is_not_a_member(graph, crew, people):
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"])
    polls.vote(graph, poll_id=opened["poll_id"], option=0, account_id=people["bo"])
    crews.block(graph, crew, people["bo"], by=people["ana"])
    with pytest.raises(polls.PollError):
        polls.vote(graph, poll_id=opened["poll_id"], option=1, account_id=people["bo"])


def test_a_poll_needs_a_question_and_at_least_two_options(graph, crew, people):
    with pytest.raises(polls.PollError):
        polls.open_poll(graph, crew_id=crew, question="", options=OPTIONS,
                        account_id=people["ana"])
    with pytest.raises(polls.PollError, match="at least"):
        polls.open_poll(graph, crew_id=crew, question=QUESTION, options=["one"],
                        account_id=people["ana"])
    with pytest.raises(polls.PollError, match="at least"):
        # Duplicates collapse, so "dinner, dinner" is one option, not two.
        polls.open_poll(graph, crew_id=crew, question=QUESTION,
                        options=["dinner", "Dinner"], account_id=people["ana"])


def test_a_closed_poll_takes_no_more_votes(graph, crew, people):
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"])
    polls.close_poll(graph, poll_id=opened["poll_id"], account_id=people["ana"])
    with pytest.raises(polls.PollError, match="closed"):
        polls.vote(graph, poll_id=opened["poll_id"], option=0, account_id=people["bo"])


def test_only_the_opener_or_an_admin_closes_it(graph, crew, people):
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["bo"])
    with pytest.raises(polls.PollError, match="only whoever opened it"):
        polls.close_poll(graph, poll_id=opened["poll_id"], account_id=people["cy"])
    # The crew's admin can.
    assert polls.close_poll(graph, poll_id=opened["poll_id"],
                            account_id=people["ana"])["closed"] is True


def test_an_expired_poll_is_closed_without_anybody_closing_it(graph, crew, people, monkeypatch):
    import datetime
    opened = polls.open_poll(graph, crew_id=crew, question=QUESTION, options=OPTIONS,
                             account_id=people["ana"], hours=1)
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    monkeypatch.setattr(polls, "_now", lambda: later)
    with pytest.raises(polls.PollError, match="closed"):
        polls.vote(graph, poll_id=opened["poll_id"], option=0, account_id=people["bo"])
    assert polls.for_crew(graph, crew_id=crew, account_id=people["ana"])["empty"] is True


# ---- beacons -----------------------------------------------------------------

def test_a_beacon_never_claims_it_was_delivered(graph, crew, people):
    """The prop said "⚡ Outing Squad Beacon broadcasted!" and sent nothing anywhere."""
    out = beacons.raise_beacon(graph, crew_id=crew, activity="coffee then bouldering",
                               account_id=people["ana"], handle="ana", minutes=30)
    assert out["push_delivered"] is False
    assert out["can_see_it"] == 2          # bo and cy could read it; nobody was told
    assert "broadcast" not in str(out).lower()


def test_a_beacon_is_answerable(graph, crew, people):
    """A beacon nobody can say "I'm in" to is a broadcast into the void."""
    raised = beacons.raise_beacon(graph, crew_id=crew, activity="coffee",
                                  account_id=people["ana"], handle="ana")
    out = beacons.join(graph, beacon_id=raised["beacon_id"], account_id=people["bo"], handle="bo")
    assert out["coming"] == ["bo"]
    assert out["coming_count"] == 1

    seen = beacons.live(graph, crew_id=crew, account_id=people["cy"])["beacons"][0]
    assert seen["coming"] == ["bo"] and seen["you_are_in"] is False


def test_joining_twice_does_not_double_the_count(graph, crew, people):
    raised = beacons.raise_beacon(graph, crew_id=crew, activity="coffee", account_id=people["ana"])
    beacons.join(graph, beacon_id=raised["beacon_id"], account_id=people["bo"], handle="bo")
    out = beacons.join(graph, beacon_id=raised["beacon_id"], account_id=people["bo"], handle="bo")
    assert out["already"] is True and out["coming_count"] == 1


def test_changing_your_mind_removes_you(graph, crew, people):
    raised = beacons.raise_beacon(graph, crew_id=crew, activity="coffee", account_id=people["ana"])
    beacons.join(graph, beacon_id=raised["beacon_id"], account_id=people["bo"], handle="bo")
    out = beacons.leave(graph, beacon_id=raised["beacon_id"], account_id=people["bo"])
    assert out["was_in"] is True and out["coming_count"] == 0


def test_a_beacon_needs_an_activity(graph, crew, people):
    """It defaulted to "Coffee & Quick Bouldering", so an empty form told your crew you were
    doing something you had not said."""
    with pytest.raises(beacons.BeaconError, match="up for what"):
        beacons.raise_beacon(graph, crew_id=crew, activity="", account_id=people["ana"])


def test_one_live_beacon_each(graph, crew, people):
    beacons.raise_beacon(graph, crew_id=crew, activity="coffee", account_id=people["ana"])
    beacons.raise_beacon(graph, crew_id=crew, activity="bouldering", account_id=people["ana"])
    live = beacons.live(graph, crew_id=crew, account_id=people["ana"])["beacons"]
    assert len(live) == 1 and live[0]["activity"] == "bouldering"


def test_an_expired_beacon_is_simply_gone(graph, crew, people, monkeypatch):
    import datetime
    beacons.raise_beacon(graph, crew_id=crew, activity="coffee", account_id=people["ana"],
                         minutes=30)
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    monkeypatch.setattr(beacons, "_now", lambda: later)
    out = beacons.live(graph, crew_id=crew, account_id=people["ana"])
    assert out["empty"] is True and out["suggestion"]


def test_a_non_member_can_neither_see_nor_join(graph, crew, people):
    raised = beacons.raise_beacon(graph, crew_id=crew, activity="coffee", account_id=people["ana"])
    with pytest.raises(beacons.BeaconError, match="no such beacon"):
        beacons.live(graph, crew_id=crew, account_id=people["stranger"])
    with pytest.raises(beacons.BeaconError, match="no such beacon"):
        beacons.join(graph, beacon_id=raised["beacon_id"], account_id=people["stranger"])


def test_only_its_owner_stands_it_down(graph, crew, people):
    raised = beacons.raise_beacon(graph, crew_id=crew, activity="coffee", account_id=people["ana"])
    with pytest.raises(beacons.BeaconError, match="not yours"):
        beacons.stand_down(graph, beacon_id=raised["beacon_id"], account_id=people["bo"])
    assert beacons.stand_down(graph, beacon_id=raised["beacon_id"],
                              account_id=people["ana"])["stood_down"] is True
    assert beacons.live(graph, crew_id=crew, account_id=people["ana"])["empty"] is True


def test_minutes_are_bounded(graph, crew, people):
    for bad in (0, 4, 60 * 24, "soon"):
        with pytest.raises(beacons.BeaconError):
            beacons.raise_beacon(graph, crew_id=crew, activity="coffee",
                                 account_id=people["ana"], minutes=bad)
