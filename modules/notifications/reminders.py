"""Reminders that exist as rows, and are honest about never being pushed.

`/notifications/schedule` returned `{"scheduled": True, "am_time": "08:00", "pm_time":
"21:00"}` — it echoed the two times back and stored nothing. Nothing was scheduled, nothing
fired, and the next request knew nothing about the last one.

**This app cannot send a notification.** There is no VAPID key pair anywhere in the repo, no
`pushManager` subscription in the PWA, no APNs certificate and no SMS provider. A reminder
here is something *waiting for you when you next open the app* — which is a genuinely useful
thing, and is the only thing that is true.

So the shape is: you say what you want reminding about and when; the row is real; opening
the app tells you what came due; and `push_delivered` is false on every response, because
somebody who believes their phone will buzz behaves differently from somebody who knows it
will not.

Times are stored as a local wall-clock string plus a UTC offset in minutes, rather than as
an instant. "Remind me at 08:00" means eight in the morning wherever the person wakes up,
and this app is built for somebody who is travelling — an instant computed once in Lisbon is
wrong the moment they land anywhere else.
"""

import datetime
import re

from substrate import now_iso
from substrate.graph import Graph

MODULE = "notifications.reminders"
SCOPES = {"content:read", "content:write"}
RECORD = "reminder"

MAX_TEXT = 200
MAX_PER_ACCOUNT = 20
MAX_DUE = 50

NOT_PUSHED = ("Nothing is pushed. This app has no push key, no APNs certificate and no SMS "
              "provider — a reminder is here waiting when you next open it.")

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ReminderError(ValueError):
    """A reminder that cannot be set or read."""


def _own(graph: Graph):
    return graph.session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _text(value, cap: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:cap]


def clock(value) -> str:
    """A 24-hour wall-clock time, or an error naming what was wrong with it."""
    text = str(value or "").strip()
    if not _TIME.match(text):
        raise ReminderError(f"{text or 'that'} is not a time — use 08:00")
    hour, minute = text.split(":")
    return f"{int(hour):02d}:{minute}"


def _days(value) -> list[str]:
    """Which days it repeats on. Empty means every day."""
    if value in (None, "", [], ()):
        return list(DAYS)
    if isinstance(value, str):
        value = value.split(",")
    chosen = []
    for item in value:
        day = str(item or "").strip().lower()[:3]
        if day not in DAYS:
            raise ReminderError(f"{item} is not a day — use mon, tue, wed…")
        if day not in chosen:
            chosen.append(day)
    if not chosen:
        raise ReminderError("which days?")
    return chosen


def _offset(value) -> int:
    """Minutes east of UTC. A reminder is set in the time zone the person is standing in."""
    if value in (None, ""):
        return 0
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        raise ReminderError("offset is a number of minutes from UTC")
    if not -14 * 60 <= minutes <= 14 * 60:
        raise ReminderError("that offset is not a real time zone")
    return minutes


def set_reminder(graph: Graph, *, account_id: str, text: str, at: str, days=None,
                 utc_offset_minutes=0, source: str = MODULE) -> dict:
    """Ask to be reminded of something, at a wall-clock time, on some days."""
    if not account_id:
        raise ReminderError("sign in first")
    text = _text(text)
    if not text:
        raise ReminderError("remind you of what?")
    at = clock(at)
    chosen = _days(days)
    offset = _offset(utc_offset_minutes)

    session = _own(graph)
    existing = [r for r in session.find_entities("content", {"type": RECORD}, limit=200)
                if not r["attrs"].get("cancelled")]
    if len(existing) >= MAX_PER_ACCOUNT:
        raise ReminderError(f"that is more than {MAX_PER_ACCOUNT} reminders")

    reminder_id = session.create_entity("content", {
        "type": RECORD, "text": text, "at": at, "days": chosen,
        "utc_offset_minutes": offset, "created_at": now_iso(),
        "last_acknowledged": "", "cancelled": False,
    }, source=source)
    return {"set": True, "reminder_id": reminder_id, "text": text, "at": at,
            "days": chosen, "push_delivered": False, "delivery_note": NOT_PUSHED}


def _local(now: datetime.datetime, offset: int) -> datetime.datetime:
    return now + datetime.timedelta(minutes=offset)


def _due_at(attrs: dict, now: datetime.datetime):
    """The most recent moment this reminder came due, or None if it has not yet.

    Computed in the reminder's own zone: the day it fires on and the hour it fires at are
    both local facts, and deciding "is it past 08:00" in UTC gets both wrong for anybody who
    is not sitting on the meridian.

    It looks back rather than only at today, because a reminder that came due while the app
    was closed is exactly the one worth still showing — that is the whole delivery mechanism
    here. But it never looks back past the moment the reminder was created: setting a daily
    07:00 nudge at lunchtime should not immediately announce that you missed this morning's.
    """
    offset = int(attrs.get("utc_offset_minutes", 0) or 0)
    local = _local(now, offset)
    hour, minute = (int(part) for part in str(attrs.get("at", "00:00")).split(":"))
    days = list(attrs.get("days") or DAYS)
    created = _parse(attrs.get("created_at", ""))

    for back in range(0, 8):
        day = local - datetime.timedelta(days=back)
        if DAYS[day.weekday()] not in days:
            continue
        moment = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment > local:
            continue
        utc_moment = moment - datetime.timedelta(minutes=offset)
        if created and utc_moment < created:
            return None
        return utc_moment
    return None


def due(graph: Graph, *, account_id: str, now=None, limit: int = MAX_DUE) -> dict:
    """What came due and has not been seen yet.

    This is the whole delivery mechanism, and it is a read. Opening the app is what
    "delivers" a reminder here — there is nothing else, and saying otherwise is the failure
    this replaces.
    """
    if not account_id:
        raise ReminderError("sign in first")
    now = now or _now()
    items = []
    for row in _own(graph).find_entities("content", {"type": RECORD}, limit=200):
        attrs = row["attrs"]
        if attrs.get("cancelled"):
            continue
        moment = _due_at(attrs, now)
        if moment is None:
            continue
        seen = _parse(attrs.get("last_acknowledged", ""))
        if seen and seen >= moment:
            continue
        items.append({"reminder_id": row["id"], "text": attrs.get("text", ""),
                      "at": attrs.get("at", ""),
                      "due_at": moment.isoformat(),
                      "minutes_late": int((now - moment).total_seconds() // 60)})
    items.sort(key=lambda r: r["due_at"])
    return {"due": items[:limit], "count": len(items), "empty": not items,
            "push_delivered": False, "delivery_note": NOT_PUSHED}


def acknowledge(graph: Graph, *, account_id: str, reminder_id: str = "", now=None,
                source: str = MODULE) -> dict:
    """Mark reminders seen, so they stop being due until the next time they come round."""
    if not account_id:
        raise ReminderError("sign in first")
    now = now or _now()
    session = _own(graph)
    cleared = 0
    for row in session.find_entities("content", {"type": RECORD}, limit=200):
        if reminder_id and row["id"] != reminder_id:
            continue
        if row["attrs"].get("cancelled"):
            continue
        session.update_entity(row["id"], {"last_acknowledged": now.isoformat()},
                              source=source)
        cleared += 1
    if reminder_id and not cleared:
        raise ReminderError("no such reminder")
    return {"acknowledged": True, "cleared": cleared}


def cancel(graph: Graph, *, account_id: str, reminder_id: str,
           source: str = MODULE) -> dict:
    if not account_id:
        raise ReminderError("sign in first")
    session = _own(graph)
    row = session.get_entity(str(reminder_id or "").strip())
    if row is None or row["attrs"].get("type") != RECORD:
        raise ReminderError("no such reminder")
    session.update_entity(row["id"], {"cancelled": True}, source=source)
    return {"cancelled": True, "reminder_id": row["id"]}


def listing(graph: Graph, *, account_id: str) -> dict:
    if not account_id:
        raise ReminderError("sign in first")
    items = [{"reminder_id": r["id"], "text": r["attrs"].get("text", ""),
              "at": r["attrs"].get("at", ""), "days": list(r["attrs"].get("days") or []),
              "created_at": r["attrs"].get("created_at", "")}
             for r in _own(graph).find_entities("content", {"type": RECORD}, limit=200)
             if not r["attrs"].get("cancelled")]
    items.sort(key=lambda r: (r["at"], r["created_at"]))
    return {"reminders": items, "empty": not items,
            "push_delivered": False, "delivery_note": NOT_PUSHED}
