"""Scheduled refresh — the politeness floor, and a loop that survives a bad pass.

Ingested content that silently stops updating is worse than less content: a digest showing
last month's listings looks exactly like one showing this month's, until somebody turns up
at a club on the wrong night.
"""

import datetime

import pytest

from modules.feeds import ingest
from tools import feedsync

def _ics_tomorrow():
    """Nothing in this file passes `now=`, so every assertion here runs against the real
    clock. A hardcoded DTSTART therefore has a shelf life of `ingest.STALE_DAYS` days from
    the day it is typed, after which `added` drops to zero and tests about *scheduling* start
    failing for reasons that have nothing to do with scheduling."""
    when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    return ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nSUMMARY:Night\n"
            f"DTSTART:{when.strftime('%Y%m%dT%H%M%SZ')}\n"
            f"DTEND:{(when + datetime.timedelta(hours=5)).strftime('%Y%m%dT%H%M%SZ')}\n"
            "END:VEVENT\nEND:VCALENDAR\n")


ICS = _ics_tomorrow()


@pytest.fixture
def feeds(graph, monkeypatch):
    monkeypatch.setattr(ingest, "_fetch", lambda url: ICS)
    for i in range(3):
        ingest.add_feed(graph, f"https://v{i}.example/e.ics", city="Lisbon", venue=f"V{i}")
    return graph


def _later(minutes: int) -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=minutes)).isoformat()


# ---- the politeness floor ----------------------------------------------------

def test_a_fresh_feed_is_skipped_rather_than_refetched(feeds):
    """Without this, a scheduler firing every ten minutes hits every venue every ten
    minutes forever — and 'a feed is published to be read' stops being a fair argument."""
    first = ingest.sync_all(feeds, min_interval_minutes=360)
    assert first["feeds"] == 3 and first["skipped_recent"] == []

    second = ingest.sync_all(feeds, min_interval_minutes=360)
    assert second["feeds"] == 0 and len(second["skipped_recent"]) == 3


def test_a_rested_feed_is_fetched_again(feeds):
    ingest.sync_all(feeds, min_interval_minutes=360)
    later = ingest.sync_all(feeds, min_interval_minutes=360, now=_later(361))
    assert later["feeds"] == 3 and later["skipped_recent"] == []


def test_no_interval_means_always_sync(feeds):
    ingest.sync_all(feeds)
    assert ingest.sync_all(feeds)["feeds"] == 3


def test_a_never_synced_feed_is_never_considered_recent(graph, monkeypatch):
    monkeypatch.setattr(ingest, "_fetch", lambda url: ICS)
    ingest.add_feed(graph, "https://new.example/e.ics")
    assert ingest.sync_all(graph, min_interval_minutes=10_000)["feeds"] == 1


def test_skipped_feeds_are_reported_not_silently_dropped(feeds):
    """A scheduler doing nothing must look different from one that is not running."""
    ingest.sync_all(feeds, min_interval_minutes=360)
    result = ingest.sync_all(feeds, min_interval_minutes=360)
    assert sorted(result["skipped_recent"]) == [f"https://v{i}.example/e.ics" for i in range(3)]


# ---- the runner --------------------------------------------------------------

def test_run_once_syncs_and_reports(feeds):
    result = feedsync.run_once(feeds, min_interval_minutes=0)
    assert result["feeds"] == 3 and result["added"] == 3


def test_the_log_line_is_skimmable(feeds):
    line = feedsync.describe(feedsync.run_once(feeds, 0),
                             now=datetime.datetime(2026, 8, 4, 9, 0, 0))
    assert line.startswith("2026-08-04T09:00:00Z")
    assert "synced=3" in line and "added=3" in line and "skipped_recent=0" in line
    assert "FAILED" not in line


def test_a_failing_feed_is_named_in_the_log(graph, monkeypatch):
    monkeypatch.setattr(ingest, "_fetch",
                        lambda url: (_ for _ in ()).throw(OSError("refused")))
    ingest.add_feed(graph, "https://dead.example/e.ics")
    assert "FAILED=https://dead.example/e.ics" in feedsync.describe(
        feedsync.run_once(graph, 0))


def test_the_loop_survives_a_bad_pass(feeds, monkeypatch, capsys):
    """A scheduler that dies on one bad pass is not a scheduler."""
    monkeypatch.setattr(feedsync, "_graph", lambda cfg: feeds)
    monkeypatch.setattr(feedsync, "load_config", lambda path: {})
    monkeypatch.setattr(feedsync, "run_once",
                        lambda g, i: (_ for _ in ()).throw(RuntimeError("boom")))

    feedsync.main(["--once"])
    assert "SYNC FAILED RuntimeError: boom" in capsys.readouterr().err


def test_once_runs_a_single_pass_and_returns(feeds, monkeypatch, capsys):
    monkeypatch.setattr(feedsync, "_graph", lambda cfg: feeds)
    monkeypatch.setattr(feedsync, "load_config", lambda path: {})
    monkeypatch.setattr(feedsync.time, "sleep",
                        lambda s: pytest.fail("--once must not sleep"))
    feedsync.main(["--once"])
    assert "synced=3" in capsys.readouterr().out


def test_the_compose_service_runs_the_tool():
    """The politeness floor only helps if the deployed command actually passes it."""
    import pathlib
    compose = pathlib.Path("deploy/vps/compose.yml").read_text()
    assert "python -m tools.feedsync" in compose
    assert "--interval" in compose and "--sleep" in compose
