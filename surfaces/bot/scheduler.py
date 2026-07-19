"""Weekly cadence for the Telegram surface.

Jobs (times in owner.timezone):
  monday_plan   Mon 07:00  -> plan the week, push it
  sunday_retro  Sun 19:00  -> score the week, push the retro
  calendar_sync daily 06:30 -> ICS free/busy into the graph (if configured)

Late-start safe: a job fires the first tick at/after its time that day.
Restart safe: runs are recorded as metric entities {type: job_run, job, date}.
"""

import datetime
import threading
import time

from modules.calendars import freebusy
from modules.horizon import planner, retro

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

# (name, weekday 0=Mon..6=Sun or None=daily, hour, minute)
JOBS = [
    ("monday_plan", 0, 7, 0),
    ("sunday_retro", 6, 19, 0),
    ("calendar_sync", None, 6, 30),
]

SCOPES = {"metrics:read", "metrics:write"}


def due_jobs(now: datetime.datetime, ran_today: set[str]) -> list[str]:
    out = []
    for name, weekday, hour, minute in JOBS:
        if name in ran_today:
            continue
        if weekday is not None and now.weekday() != weekday:
            continue
        if (now.hour, now.minute) >= (hour, minute):
            out.append(name)
    return out


class Scheduler(threading.Thread):
    def __init__(self, bot, cfg: dict, graph, claude):
        super().__init__(daemon=True, name="lifeos-scheduler")
        self.bot = bot
        self.cfg = cfg
        self.graph = graph
        self.claude = claude
        self.owner_chat_id = cfg.get("telegram", {}).get("owner_chat_id", "")
        tzname = cfg.get("owner", {}).get("timezone", "UTC")
        self.tz = ZoneInfo(tzname) if ZoneInfo and tzname else datetime.timezone.utc

    # ---- run-once-per-day guard (graph-backed, restart safe) -------------

    def _ran_today(self, date_str: str) -> set[str]:
        session = self.graph.session("scheduler", SCOPES)
        runs = session.find_entities("metric", {"type": "job_run", "date": date_str}, limit=50)
        return {r["attrs"].get("job") for r in runs}

    def _record(self, job: str, date_str: str) -> None:
        session = self.graph.session("scheduler", SCOPES)
        session.create_entity("metric", {"type": "job_run", "job": job, "date": date_str}, source="scheduler")

    # ---- jobs ------------------------------------------------------------

    def run_job(self, name: str) -> None:
        if name == "monday_plan":
            result = planner.plan_week(self.graph, claude=self.claude)
            self._send("Good morning. " + planner.format_week(self.graph, result["week"]))
        elif name == "sunday_retro":
            self._send(retro.run_retro(self.graph, claude=self.claude)["text"])
        elif name == "calendar_sync":
            if self.cfg.get("calendar", {}).get("ics_url"):
                freebusy.sync(self.graph, self.cfg)

    def _send(self, text: str) -> None:
        self.bot._api("sendMessage", chat_id=int(self.owner_chat_id), text=text)

    # ---- loop ------------------------------------------------------------

    def tick(self, now: datetime.datetime | None = None) -> list[str]:
        now = now or datetime.datetime.now(self.tz)
        date_str = now.date().isoformat()
        fired = []
        for job in due_jobs(now, self._ran_today(date_str)):
            self._record(job, date_str)  # record first: a crashing job must not retry-spam
            try:
                self.run_job(job)
                fired.append(job)
            except Exception as exc:
                print(f"[scheduler] job {job} failed: {exc}")
        return fired

    def run(self):
        print(f"[scheduler] started (tz={self.tz})")
        while True:
            try:
                self.tick()
            except Exception as exc:
                print(f"[scheduler] tick failed: {exc}")
            time.sleep(60)
