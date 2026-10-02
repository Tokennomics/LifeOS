"""The agent's morning check-in, pushed — once a day, and only when something needs you.

Muse's habit that the in-app agent could not copy was coming back on its own. The agent's
"needs you" list (approvals waiting, deadlines close or passed, goals stalled a week) only
existed when you opened the app. This sends it to the phone each morning.

Rules, because a notification nobody asked for is the fastest way to lose a user:

- **Opt-in per device.** Only subscriptions with `checkin: true` get one, and turning
  notifications on in the agent card is the only way to make one.
- **Local morning.** Sent at `CHECKIN_HOUR` in the timezone the browser reported when it
  subscribed, never at 08:00 UTC to somebody in Lisbon at 09:00 or in Tokyo at 17:00.
- **Once per day per device**, whether it was sent or skipped.
- **Quiet days are quiet.** If nothing needs you, nothing is sent; the day is marked done.
- **Truthful about delivery.** The result is what the push service said.

The loop is a daemon thread like `feeds.autosync`, started only when
`LIFEOS_PUSH_CHECKINS` is set, so no test or laptop starts one.
"""

import datetime
import os
import threading
import time
import zoneinfo

from substrate import now_iso
from substrate.graph import Graph

from modules.notifications import webpush

MODULE = "notifications.checkins"
ENABLE_VAR = "LIFEOS_PUSH_CHECKINS"
CHECKIN_HOUR = 8
TICK_SECONDS = 600

_STARTED = False


def _local_now(tz: str, now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        return now.astimezone(zoneinfo.ZoneInfo(tz or "UTC"))
    except Exception:
        return now


def message_for(graph: Graph) -> dict | None:
    """The check-in as a notification, or None when nothing needs you."""
    from modules.agent import core

    c = core.checkin(graph)
    if c["quiet"]:
        return None
    lines = [i["why"] for i in c["needs_you"]][:3]
    body = "\n".join(lines)
    if len(c["needs_you"]) > 3:
        body += f"\n…and {len(c['needs_you']) - 3} more"
    return {"title": "Your morning check-in", "body": body[:240], "url": "/app/#agent",
            "tag": "lifeos-checkin"}


def run_once(graph: Graph, *, now: datetime.datetime | None = None, post=None) -> dict:
    """Every subscribed device whose local morning has come and that has not had today's."""
    everyone = Graph(graph.conn, graph.bus, default_owner=None)
    rows = everyone.session(MODULE, webpush.SCOPES).find_entities(
        "content", {"type": webpush.SUB_RECORD}, limit=5000)
    sent = skipped_quiet = not_due = 0
    results = []
    for row in rows:
        a = row["attrs"]
        if not a.get("checkin", True):
            continue
        local = _local_now(a.get("timezone", "UTC"), now)
        today = local.date().isoformat()
        if local.hour < CHECKIN_HOUR or a.get("last_checkin") == today:
            not_due += 1
            continue
        owner = Graph(graph.conn, graph.bus, default_owner=row["owner_id"])
        owner.session(MODULE, webpush.SCOPES).update_entity(
            row["id"], {"last_checkin": today}, source=MODULE)
        message = message_for(owner)
        if message is None:
            skipped_quiet += 1
            continue
        result = webpush.send(owner, row, message, post=post, source=MODULE)
        results.append(result)
        sent += 1 if result["push_delivered"] else 0
    return {"at": now_iso(), "delivered": sent, "quiet": skipped_quiet, "not_due": not_due,
            "results": results}


def _loop(graph: Graph):
    while True:
        try:
            run_once(graph)
        except Exception as exc:                  # never let the thread die
            print(f"[checkins] pass failed: {type(exc).__name__}: {exc}")
        time.sleep(TICK_SECONDS)


def enabled() -> bool:
    return str(os.environ.get(ENABLE_VAR, "")).strip().lower() in {"1", "true", "yes", "on"}


def start(graph: Graph) -> bool:
    global _STARTED
    if not enabled() or _STARTED:
        return False
    _STARTED = True
    threading.Thread(target=_loop, args=(graph,), name="lifeos-checkins", daemon=True).start()
    print("[checkins] on: morning check-ins at "
          f"{CHECKIN_HOUR:02d}:00 local per device")
    return True
