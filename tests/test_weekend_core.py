"""The weekend window, buckets and rendering — pure, so every case is a fixed clock."""

import pytest

from modules.weekend import core

# 2026-08-04 is a Tuesday. That week's weekend is Fri 7 – Sun 9 August.
TUE = "2026-08-04T09:00:00+00:00"
THU = "2026-08-06T23:30:00+00:00"
FRI_MORNING = "2026-08-07T08:00:00+00:00"
SAT_AFTERNOON = "2026-08-08T15:00:00+00:00"
SUN_NIGHT = "2026-08-09T22:00:00+00:00"
MON = "2026-08-10T09:00:00+00:00"


@pytest.mark.parametrize("now", [TUE, THU, FRI_MORNING, SAT_AFTERNOON, SUN_NIGHT])
def test_every_day_up_to_sunday_night_points_at_the_same_weekend(now):
    """Opening this on Saturday morning must not show you next weekend. That is the one
    moment the thing is most likely to be opened."""
    w = core.weekend_window(now)
    assert w["start"] == "2026-08-07T18:00:00"
    assert w["end"].startswith("2026-08-09T23:59")


def test_monday_rolls_on_to_the_next_one(now=MON):
    assert core.weekend_window(now)["start"] == "2026-08-14T18:00:00"


def test_the_window_knows_whether_it_is_already_underway(now=None):
    assert core.weekend_window(TUE)["is_underway"] is False
    assert core.weekend_window(SAT_AFTERNOON)["is_underway"] is True
    assert core.weekend_window(SAT_AFTERNOON, offset=1)["is_underway"] is False, \
        "a future weekend is never 'underway', even asked for on a Saturday"


@pytest.mark.parametrize("offset,expected", [
    (0, "2026-08-07T18:00:00"), (1, "2026-08-14T18:00:00"), (-1, "2026-07-31T18:00:00")])
def test_offset_moves_whole_weeks(offset, expected):
    assert core.weekend_window(TUE, offset=offset)["start"] == expected


def test_the_days_are_labelled_for_a_human(now=TUE):
    assert [d["label"] for d in core.weekend_window(TUE)["days"]] == ["FRI 7", "SAT 8", "SUN 9"]
    assert [d["date"] for d in core.weekend_window(TUE)["days"]] == [
        "2026-08-07", "2026-08-08", "2026-08-09"]


def test_a_span_across_two_months_says_both(now=None):
    w = core.weekend_window("2026-07-29T09:00:00+00:00")     # Fri 31 Jul – Sun 2 Aug
    assert w["label"] == "31 Jul – 2 Aug"
    assert core.weekend_window(TUE)["label"] == "7–9 Aug"


# ---- timezones ---------------------------------------------------------------

def test_the_weekend_boundary_moves_with_the_timezone():
    """18:00 UTC Friday is 10:00 in California. Bucketing in UTC puts a Friday-night party
    on Saturday for anyone west of it."""
    late_friday = "2026-08-08T02:30:00+00:00"       # 18:30 Fri in UTC-8, Saturday in UTC
    assert core.bucket([{"start": late_friday, "title": "party"}],
                       core.weekend_window(TUE))["2026-08-08"], "UTC calls it Saturday"

    shifted = core.weekend_window(TUE, tz_offset_minutes=-480)
    friday = core.bucket([{"start": late_friday, "title": "party"}], shifted,
                         tz_offset_minutes=-480)["2026-08-07"]
    assert [i["at"] for i in friday] == ["18:30"], "locally it is Friday night"


# ---- what counts as "this weekend" -------------------------------------------

@pytest.mark.parametrize("start,expected", [
    ("2026-08-07T17:59:00+00:00", False),   # Friday, but before the weekend starts
    ("2026-08-07T18:00:00+00:00", True),
    ("2026-08-09T23:00:00+00:00", True),
    ("2026-08-10T00:30:00+00:00", False),   # Sunday's small hours are Monday
    ("2026-08-06T21:00:00+00:00", False),
])
def test_the_edges_of_the_window(start, expected):
    assert core.in_window(start, core.weekend_window(TUE)) is expected


def test_an_undated_thing_is_not_in_the_weekend():
    """`discover._in_window` counts undated as always matching — right for a trip filter,
    wrong for a claim about when something is."""
    for blank in ("", None, "   ", "sometime"):
        assert core.in_window(blank, core.weekend_window(TUE)) is False


def test_a_bare_date_is_a_legitimate_way_to_say_when():
    assert core.in_window("2026-08-08", core.weekend_window(TUE)) is True


def test_a_malformed_date_is_dropped_not_raised():
    """A digest must not blow up because one row was hand-typed."""
    window = core.weekend_window(TUE)
    rows = core.bucket([{"start": "next tuesday-ish", "title": "x"},
                        {"start": "2026-08-08T20:00:00+00:00", "title": "ok"}], window)
    assert [i["title"] for day in rows.values() for i in day] == ["ok"]


# ---- buckets -----------------------------------------------------------------

def test_items_land_on_their_day_earliest_first():
    window = core.weekend_window(TUE)
    rows = core.bucket([
        {"start": "2026-08-08T22:00:00+00:00", "title": "late"},
        {"start": "2026-08-08T19:00:00+00:00", "title": "early"},
        {"start": "2026-08-07T20:00:00+00:00", "title": "friday"},
    ], window)
    assert [i["title"] for i in rows["2026-08-08"]] == ["early", "late"]
    assert [i["title"] for i in rows["2026-08-07"]] == ["friday"]
    assert rows["2026-08-09"] == []
    assert rows["2026-08-08"][0]["at"] == "19:00"


# ---- the text ----------------------------------------------------------------

def _digest(**over):
    window = core.weekend_window(TUE)
    base = {"city": "Lisbon", "label": window["label"], "is_underway": False,
            "when_label": "this weekend", "crews": [],
            "days": [{**d, "yours": [], "open": []} for d in window["days"]]}
    return {**base, **over}


def test_the_rendering_is_pasteable():
    window = core.weekend_window(TUE)
    days = [{**d, "yours": [], "open": []} for d in window["days"]]
    days[1]["open"] = [{"at": "20:00", "title": "Sushi night", "place": "Bairro Alto",
                        "going_count": 6}]
    days[1]["yours"] = [{"at": "10:00", "title": "Dentist"}]
    text = core.render(_digest(days=days))

    assert text.startswith("Lisbon — this weekend (7–9 Aug)")
    assert "  20:00 Sushi night @ Bairro Alto · 6 in" in text
    assert "  10:00 Dentist  (yours)" in text
    assert "*" not in text and "|" not in text, "must survive a paste into a chat"
    assert text.endswith("\n")


def test_an_empty_day_says_so_rather_than_vanishing():
    assert "\n  —\n" in core.render(_digest())


def test_an_empty_weekend_names_the_crews_who_could_fix_it():
    """The atomic network is one crew that meets twice. A digest that invented events would
    hide the exact signal that matters."""
    text = core.render(_digest(crews=[{"title": "Lisbon Sushi Club"},
                                      {"title": "Cais Climbers"}]))
    assert "2 crews here: Lisbon Sushi Club, Cais Climbers" in text
    assert "Someone has to go first" in text


def test_one_crew_is_a_crew_not_a_crew_s():
    assert "1 crew here: Cais Climbers" in core.render(
        _digest(crews=[{"title": "Cais Climbers"}]))


# ---- a weekend already under way ---------------------------------------------

def _weekend_days(**rows):
    window = core.weekend_window(TUE)
    return [{**d, "yours": rows.get(d["date"], {}).get("yours", []),
             "open": rows.get(d["date"], {}).get("open", [])} for d in window["days"]]


def test_mid_weekend_drops_what_you_already_missed():
    """Opened at 15:00 Saturday, the untrimmed digest leads with Friday's party and that
    morning's dentist appointment — a list of what you missed, at the moment someone is
    looking for what to do tonight. Found by reading the output, not by a test."""
    days = _weekend_days(**{
        "2026-08-07": {"open": [{"start": "2026-08-07T23:00:00+00:00", "title": "Friday party"}]},
        "2026-08-08": {"yours": [{"start": "2026-08-08T10:00:00+00:00", "title": "Dentist"}],
                       "open": [{"start": "2026-08-08T21:00:00+00:00", "title": "Sushi night"}]},
    })
    kept, trimmed = core.drop_past(days, SAT_AFTERNOON)
    assert trimmed is True
    assert [d["date"] for d in kept] == ["2026-08-08", "2026-08-09"], "Friday is gone"
    assert [i["title"] for i in kept[0]["open"]] == ["Sushi night"]
    assert kept[0]["yours"] == [], "this morning's dentist is not tonight's problem"


def test_something_that_started_an_hour_ago_has_not_finished():
    """A club night at 23:00 is still the answer at 23:45."""
    days = _weekend_days(**{
        "2026-08-08": {"open": [{"start": "2026-08-08T14:00:00+00:00", "title": "just started"},
                                {"start": "2026-08-08T11:00:00+00:00", "title": "long over"}]}})
    kept, _ = core.drop_past(days, SAT_AFTERNOON)
    assert [i["title"] for i in kept[0]["open"]] == ["just started"]


def test_nothing_is_trimmed_when_the_weekend_has_not_started():
    days = _weekend_days(**{
        "2026-08-07": {"open": [{"start": "2026-08-07T23:00:00+00:00", "title": "Friday party"}]}})
    kept, trimmed = core.drop_past(days, TUE)
    assert trimmed is False and len(kept) == 3


def test_an_empty_weekend_with_no_crews_is_still_honest():
    assert "Nothing published for this weekend yet." in core.render(_digest())


def test_an_untitled_item_still_renders():
    days = [{"date": "2026-08-07", "label": "FRI 7", "yours": [],
             "open": [{"at": "21:00", "title": ""}]}]
    assert "21:00 untitled" in core.render(_digest(days=days))
