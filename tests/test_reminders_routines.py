"""Reminders and standing crew routines.

`/notifications/schedule` echoed two times back and stored nothing — `{"scheduled": True,
"am_time": "08:00", "pm_time": "21:00"}` — so nothing was scheduled and the next request
knew nothing about the last. `/routines/squad-sync` reported `synced_calendars: 5` on a crew
that might have had no members, the same recurrence whatever you asked for, and an ics_link
on a host this deployment does not serve.

The claim both must never make is delivery. This app has no push key, no APNs certificate,
no SMS provider, and cannot add an event to anybody's calendar.
"""

import datetime

import pytest

from gateway import accounts
from modules.crews import crews
from modules.notifications import reminders
from modules.routines import squad

PW = "correct-horse-battery"
UTC = datetime.timezone.utc


@pytest.fixture
def people(graph):
    return {name: accounts.register(graph, name, PW)["account_id"]
            for name in ("ana", "bo", "stranger")}


# Monday, 2026-08-10, midnight UTC. A reminder never fires for a moment before it was
# created — setting a daily 07:00 nudge at lunchtime must not announce that you missed this
# morning's — so the creation instant has to be fixed for any of these dates to mean
# anything.
CREATED = "2026-08-10T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _created_on_a_monday(monkeypatch):
    monkeypatch.setattr(reminders, "now_iso", lambda: CREATED)


@pytest.fixture
def crew(graph, people):
    crew_id = crews.create(graph, "the regulars", visibility="private",
                           admin_id=people["ana"])["id"]
    crews.invite(graph, crew_id, people["bo"], by=people["ana"])
    crews.accept_invite(graph, crew_id, people["bo"])
    return crew_id


# ---- reminders ---------------------------------------------------------------

def test_a_reminder_is_stored_and_comes_due(graph, people):
    reminders.set_reminder(graph, account_id=people["ana"], text="stretch",
                           at="08:00", days=["mon", "tue", "wed", "thu", "fri",
                                             "sat", "sun"])
    # 09:00 on a Wednesday: 08:00 has passed.
    now = datetime.datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    out = reminders.due(graph, account_id=people["ana"], now=now)
    assert out["count"] == 1
    assert out["due"][0]["text"] == "stretch"
    assert out["due"][0]["minutes_late"] == 60


def test_one_you_never_saw_is_still_waiting(graph, people):
    """The whole delivery mechanism is that opening the app shows what came due while it was
    closed — so at 07:00 on Wednesday it is *Tuesday's* that is pending, not today's."""
    reminders.set_reminder(graph, account_id=people["ana"], text="stretch", at="08:00")
    now = datetime.datetime(2026, 8, 12, 7, 0, tzinfo=UTC)
    out = reminders.due(graph, account_id=people["ana"], now=now)
    assert out["count"] == 1
    assert out["due"][0]["due_at"].startswith("2026-08-11T08:00")


def test_a_reminder_never_fires_for_a_time_before_it_existed(graph, people):
    """Setting a daily 07:00 nudge at lunchtime must not immediately announce that you
    missed this morning's."""
    reminders.set_reminder(graph, account_id=people["ana"], text="stretch", at="08:00")
    # Created Monday 00:00; Sunday's 08:00 is before that, and Monday's has not arrived.
    just_after = datetime.datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
    assert reminders.due(graph, account_id=people["ana"], now=just_after)["empty"] is True


def test_a_reminder_only_fires_on_its_days(graph, people):
    reminders.set_reminder(graph, account_id=people["ana"], text="team call",
                           at="09:00", days=["mon"])
    wednesday = datetime.datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    out = reminders.due(graph, account_id=people["ana"], now=wednesday)
    # Monday the 10th is the most recent one, and it is still unacknowledged.
    assert out["count"] == 1
    assert out["due"][0]["due_at"].startswith("2026-08-10T09:00")

    reminders.acknowledge(graph, account_id=people["ana"], now=wednesday)
    assert reminders.due(graph, account_id=people["ana"], now=wednesday)["empty"] is True


def test_the_time_is_local_not_utc(graph, people):
    """"Remind me at 08:00" means eight where the person wakes up. An instant computed once
    in Lisbon is wrong the moment they land anywhere else — and this app is for somebody who
    is travelling, so that is the common case rather than the edge one.

    A Wednesday-only reminder, so exactly one moment is in play: 08:00 Wednesday local,
    which at UTC+9 is 23:00 on Tuesday in UTC.
    """
    reminders.set_reminder(graph, account_id=people["ana"], text="stretch", at="08:00",
                           days=["wed"], utc_offset_minutes=9 * 60)
    before = datetime.datetime(2026, 8, 11, 22, 0, tzinfo=UTC)    # 07:00 local Wednesday
    after = datetime.datetime(2026, 8, 11, 23, 30, tzinfo=UTC)    # 08:30 local Wednesday
    assert reminders.due(graph, account_id=people["ana"], now=before)["empty"] is True
    assert reminders.due(graph, account_id=people["ana"], now=after)["count"] == 1


def test_the_same_instant_is_not_due_for_somebody_in_another_zone(graph, people):
    """The contrast that proves it is local: at 23:30 UTC on Tuesday, Wednesday has started
    for the person at UTC+9 and not for the one at UTC."""
    reminders.set_reminder(graph, account_id=people["bo"], text="stretch", at="08:00",
                           days=["wed"], utc_offset_minutes=0)
    same_instant = datetime.datetime(2026, 8, 11, 23, 30, tzinfo=UTC)
    assert reminders.due(graph, account_id=people["bo"], now=same_instant)["empty"] is True


def test_acknowledging_clears_it_until_next_time(graph, people):
    reminders.set_reminder(graph, account_id=people["ana"], text="stretch", at="08:00")
    wednesday = datetime.datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    reminders.acknowledge(graph, account_id=people["ana"], now=wednesday)
    assert reminders.due(graph, account_id=people["ana"], now=wednesday)["empty"] is True

    tomorrow = datetime.datetime(2026, 8, 13, 9, 0, tzinfo=UTC)
    assert reminders.due(graph, account_id=people["ana"], now=tomorrow)["count"] == 1


def test_nothing_claims_to_have_been_pushed(graph, people):
    """There is no VAPID key, no APNs certificate and no SMS provider in this repo."""
    out = reminders.set_reminder(graph, account_id=people["ana"], text="stretch", at="08:00")
    for payload in (out, reminders.due(graph, account_id=people["ana"]),
                    reminders.listing(graph, account_id=people["ana"])):
        assert payload["push_delivered"] is False
        assert payload["delivery_note"]


def test_a_time_has_to_be_a_time(graph, people):
    for bad in ("25:00", "8am", "", "08:60", "0800", None):
        with pytest.raises(reminders.ReminderError):
            reminders.set_reminder(graph, account_id=people["ana"], text="x", at=bad)


def test_a_day_has_to_be_a_day(graph, people):
    with pytest.raises(reminders.ReminderError, match="not a day"):
        reminders.set_reminder(graph, account_id=people["ana"], text="x", at="08:00",
                               days=["someday"])


def test_a_reminder_needs_something_to_say(graph, people):
    with pytest.raises(reminders.ReminderError):
        reminders.set_reminder(graph, account_id=people["ana"], text="", at="08:00")


def test_cancelling_stops_it(graph, people):
    out = reminders.set_reminder(graph, account_id=people["ana"], text="stretch", at="08:00")
    reminders.cancel(graph, account_id=people["ana"], reminder_id=out["reminder_id"])
    now = datetime.datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    assert reminders.due(graph, account_id=people["ana"], now=now)["empty"] is True
    assert reminders.listing(graph, account_id=people["ana"])["empty"] is True


# ---- squad routines ----------------------------------------------------------

def test_a_routine_expands_into_real_dates(graph, crew, people):
    out = squad.set_routine(graph, crew_id=crew, title="dawn patrol", day="wed",
                            at="07:00", account_id=people["ana"])
    assert out["recurrence"] == "every wed at 07:00"
    assert len(out["upcoming"]) == 4
    for stamp in out["upcoming"]:
        moment = datetime.datetime.fromisoformat(stamp)
        assert moment.weekday() == 2 and moment.hour == 7


def test_the_dates_are_a_week_apart_and_in_the_future(graph, crew, people):
    now = datetime.datetime(2026, 8, 12, 12, 0, tzinfo=UTC)   # a Wednesday, after 07:00
    made = squad.set_routine(graph, crew_id=crew, title="dawn patrol", day="wed",
                             at="07:00", account_id=people["ana"])
    dates = squad.occurrences(graph, routine_id=made["routine_id"],
                              account_id=people["ana"], weeks=3, now=now)["dates"]
    moments = [datetime.datetime.fromisoformat(d) for d in dates]
    assert all(m > now for m in moments)                      # today's has passed
    assert (moments[1] - moments[0]).days == 7


def test_nothing_claims_to_have_synced_a_calendar(graph, crew, people):
    """`synced_calendars: 5` was the same lie as "your crew has been notified"."""
    out = squad.set_routine(graph, crew_id=crew, title="dawn patrol", day="wed",
                            at="07:00", account_id=people["ana"])
    assert out["calendars_synced"] == 0
    assert out["can_subscribe"] == 2
    assert out["ics_path"].endswith("/export.ics")
    assert "connectos.app" not in str(out)


def test_the_routine_reaches_the_crew_calendar_feed(graph, crew, people):
    """The part that makes "synced" mean anything: it is in the .ics this app serves."""
    from modules.calendars import export
    squad.set_routine(graph, crew_id=crew, title="dawn patrol", day="wed", at="07:00",
                      account_id=people["ana"], place="Carcavelos")
    ics = export.export_crew_ics(graph, crew)
    assert "BEGIN:VEVENT" in ics
    assert "dawn patrol" in ics
    assert "Carcavelos" in ics


def test_a_routine_needs_a_title_and_a_real_day(graph, crew, people):
    with pytest.raises(squad.RoutineError):
        squad.set_routine(graph, crew_id=crew, title="", day="wed", at="07:00",
                          account_id=people["ana"])
    with pytest.raises(squad.RoutineError, match="not a day"):
        squad.set_routine(graph, crew_id=crew, title="x", day="someday", at="07:00",
                          account_id=people["ana"])
    with pytest.raises(squad.RoutineError, match="not a time"):
        squad.set_routine(graph, crew_id=crew, title="x", day="wed", at="7am",
                          account_id=people["ana"])


def test_a_non_member_sees_nothing(graph, crew, people):
    made = squad.set_routine(graph, crew_id=crew, title="dawn patrol", day="wed",
                             at="07:00", account_id=people["ana"])
    with pytest.raises(squad.RoutineError, match="no such routine"):
        squad.for_crew(graph, crew_id=crew, account_id=people["stranger"])
    with pytest.raises(squad.RoutineError, match="no such routine"):
        squad.occurrences(graph, routine_id=made["routine_id"],
                          account_id=people["stranger"])


def test_only_whoever_set_it_or_an_admin_ends_it(graph, crew, people):
    made = squad.set_routine(graph, crew_id=crew, title="dawn patrol", day="wed",
                             at="07:00", account_id=people["bo"])
    # ana administers the crew, so she can end bo's routine; bo can end his own.
    assert squad.end(graph, routine_id=made["routine_id"],
                     account_id=people["ana"])["ended"] is True
    assert squad.for_crew(graph, crew_id=crew, account_id=people["ana"])["empty"] is True


def test_an_ended_routine_leaves_the_calendar(graph, crew, people):
    from modules.calendars import export
    made = squad.set_routine(graph, crew_id=crew, title="dawn patrol", day="wed",
                             at="07:00", account_id=people["ana"])
    squad.end(graph, routine_id=made["routine_id"], account_id=people["ana"])
    assert "dawn patrol" not in export.export_crew_ics(graph, crew)
