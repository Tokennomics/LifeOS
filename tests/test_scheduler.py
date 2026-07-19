import datetime

from surfaces.bot.scheduler import Scheduler, due_jobs


def _dt(weekday: int, hour: int, minute: int) -> datetime.datetime:
    # 2026-07-20 is a Monday
    base = datetime.date(2026, 7, 20) + datetime.timedelta(days=weekday)
    return datetime.datetime.combine(base, datetime.time(hour, minute), tzinfo=datetime.timezone.utc)


def test_due_jobs_monday_morning():
    assert due_jobs(_dt(0, 7, 5), set()) == ["monday_plan", "calendar_sync"]
    assert due_jobs(_dt(0, 6, 0), set()) == []  # before both


def test_due_jobs_weekday_and_ran_guard():
    assert due_jobs(_dt(1, 12, 0), set()) == ["calendar_sync"]  # Tuesday: only the daily job
    assert due_jobs(_dt(6, 19, 0), {"calendar_sync"}) == ["sunday_retro"]
    assert due_jobs(_dt(6, 20, 0), {"sunday_retro", "calendar_sync"}) == []


class FakeBot:
    def __init__(self):
        self.sent = []

    def _api(self, method, **params):
        self.sent.append(params)


def test_tick_fires_records_and_never_repeats(cfg, graph):
    cfg["telegram"]["owner_chat_id"] = "42"
    bot = FakeBot()
    sched = Scheduler(bot, cfg, graph, claude=None)

    monday = _dt(0, 7, 30)
    assert sched.tick(monday) == ["monday_plan", "calendar_sync"]
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == 42

    assert sched.tick(monday) == []  # graph-backed run guard
    runs = graph.session("scheduler", {"metrics:read"}).find_entities("metric", {"type": "job_run"})
    assert {r["attrs"]["job"] for r in runs} == {"monday_plan", "calendar_sync"}
