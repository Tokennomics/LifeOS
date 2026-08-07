"""What's on this weekend — the pure part: window, buckets, and the text you paste.

No graph, no I/O, no clock of its own. `now` is always passed in, which is what makes
"it's already Saturday afternoon" testable.

**The window is Friday 18:00 to Sunday end of day, and which weekend you get depends on
where you're standing.** Monday to Thursday it is the weekend coming. Friday, Saturday or
Sunday it is *the one you are in* — a digest that skips to next weekend because it is
already Saturday morning is useless exactly when someone opens it. `offset=1` is next
weekend, `-1` the one just gone.

**Times are handled in a single local frame.** Everything — `now` and every event — is
normalised once, by adding `tz_offset_minutes`, and after that the whole module thinks in
naive local time. Doing it any other way puts "Friday 18:00" an hour out in Lisbon and eight
hours out in California, which is how an event lands in the wrong day's bucket.
"""

import datetime

FRIDAY = 4
WEEKEND_STARTS_HOUR = 18
DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse(value, tz_offset_minutes: int = 0):
    """ISO string -> naive datetime in the local frame, or None.

    Tolerant on purpose: event starts are hand-typed as often as they are machine-written,
    and a digest must not blow up on one bad row.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        try:                                   # a bare date is a legitimate way to say when
            parsed = datetime.datetime.combine(
                datetime.date.fromisoformat(text[:10]), datetime.time.min)
        except (ValueError, TypeError):
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed + datetime.timedelta(minutes=tz_offset_minutes)


def weekend_window(now, offset: int = 0, tz_offset_minutes: int = 0) -> dict:
    """The weekend around `now`: when it starts, when it ends, and its three days."""
    current = parse(now, tz_offset_minutes) or datetime.datetime(1970, 1, 1)
    weekday = current.weekday()

    if weekday >= FRIDAY:
        friday = current.date() - datetime.timedelta(days=weekday - FRIDAY)
    else:
        friday = current.date() + datetime.timedelta(days=FRIDAY - weekday)
    friday += datetime.timedelta(days=7 * int(offset))

    start = datetime.datetime.combine(friday, datetime.time(WEEKEND_STARTS_HOUR))
    sunday = friday + datetime.timedelta(days=2)
    end = datetime.datetime.combine(sunday, datetime.time.max)
    days = [{"date": (friday + datetime.timedelta(days=i)).isoformat(),
             "label": f"{DAY_NAMES[(FRIDAY + i) % 7]} {(friday + datetime.timedelta(days=i)).day}"}
            for i in range(3)]
    return {"start": start.isoformat(), "end": end.isoformat(),
            "label": _span_label(friday, sunday), "days": days,
            "is_underway": weekday >= FRIDAY and offset == 0}


def _span_label(friday: datetime.date, sunday: datetime.date) -> str:
    if friday.month == sunday.month:
        return f"{friday.day}–{sunday.day} {MONTHS[sunday.month - 1]}"
    return (f"{friday.day} {MONTHS[friday.month - 1]} – "
            f"{sunday.day} {MONTHS[sunday.month - 1]}")


def in_window(start, window: dict, tz_offset_minutes: int = 0) -> bool:
    """Undated things are NOT in the weekend.

    `discover._in_window` counts an undated event as always matching, which is right for a
    trip-length filter and wrong here: "this weekend" is a claim about when, so something
    with no when cannot honour it. They come back separately, under their own heading.
    """
    when = parse(start, tz_offset_minutes)
    if when is None:
        return False
    return parse(window["start"]) <= when <= parse(window["end"])


def bucket(items, window: dict, tz_offset_minutes: int = 0) -> dict:
    """Group items by the weekend day they fall on, earliest first within each day."""
    by_date = {day["date"]: [] for day in window["days"]}
    for item in items or []:
        when = parse(item.get("start"), tz_offset_minutes)
        if when is None:
            continue
        key = when.date().isoformat()
        if key in by_date and in_window(item.get("start"), window, tz_offset_minutes):
            by_date[key].append({**item, "at": when.strftime("%H:%M")})
    for rows in by_date.values():
        rows.sort(key=lambda i: (i["at"], str(i.get("title") or "")))
    return by_date


STILL_CATCHABLE_HOURS = 2


def drop_past(days, now, tz_offset_minutes: int = 0) -> tuple[list, bool]:
    """Trim a weekend already under way down to what's left of it.

    Opened at 15:00 on Saturday, the untrimmed digest leads with Friday's party and that
    morning's dentist appointment — a list of what you already missed, at the exact moment
    someone is looking for what to do tonight.

    A thing that started an hour ago has not finished: a club night at 23:00 is still the
    answer at 23:45. So the cut is `STILL_CATCHABLE_HOURS` after the start, not the start.
    Days entirely in the past drop out rather than sitting there as empty headings.
    """
    current = parse(now, tz_offset_minutes)
    if current is None:
        return list(days), False
    cutoff = current - datetime.timedelta(hours=STILL_CATCHABLE_HOURS)

    kept, trimmed = [], False
    for day in days:
        live = {}
        for bucket_name in ("yours", "open"):
            rows = day.get(bucket_name, [])
            still = [r for r in rows
                     if (parse(r.get("start"), tz_offset_minutes) or current) >= cutoff]
            trimmed = trimmed or len(still) != len(rows)
            live[bucket_name] = still
        if day["date"] < current.date().isoformat() and not (live["yours"] or live["open"]):
            trimmed = True
            continue
        kept.append({**day, **live})
    return kept, trimmed


# ---- the text you actually send ----------------------------------------------

def _line(item: dict) -> str:
    """One event, one line.

    The `· listed` marker matters more than it looks. Once venue feeds are ingested, most
    of a weekend is public listings, and a listing is a different promise from "six people
    from your climbing crew agreed on Thursday". Blurring the two buys density by spending
    the only signal worth having, so a listing nobody has committed to says so.
    """
    bits = [item.get("at", ""), str(item.get("title") or "untitled").strip()]
    where = str(item.get("place") or "").strip()
    if where:
        bits.append(f"@ {where}")
    going = int(item.get("going_count") or 0)
    if going:
        bits.append(f"· {going} in")
    elif item.get("origin") == "feed":
        bits.append("· listed")
    return "  " + " ".join(b for b in bits if b)


def render(digest: dict) -> str:
    """A plain-text weekend, sized for a message rather than a screen.

    This is the artefact people actually share, so it is built to survive a paste into a
    chat: no markdown that renders as literal asterisks, no box drawing that wraps into
    confetti on a narrow phone, and nothing that needs a link to make sense.
    """
    where = digest.get("city") or ""
    head = f"{where} — " if where else ""
    when = digest.get("when_label", "this weekend")
    lines = [f"{head}{when} ({digest.get('label', '')})".strip(), ""]

    total = 0
    for day in digest.get("days", []):
        lines.append(day["label"])
        yours, open_ = day.get("yours", []), day.get("open", [])
        for item in yours:
            lines.append(_line(item) + "  (yours)")
        for item in open_:
            lines.append(_line(item))
        if not yours and not open_:
            lines.append("  —")
        total += len(open_)
        lines.append("")

    if not total:
        crews = digest.get("crews", [])
        if crews:
            names = ", ".join(c.get("title", "") for c in crews[:3] if c.get("title"))
            count = f"{len(crews)} crew" + ("" if len(crews) == 1 else "s")
            lines.append(f"Nothing published yet. {count} here: {names}.")
            lines.append("Someone has to go first — propose a night and it lands on this list.")
        else:
            lines.append("Nothing published for this weekend yet.")
    return "\n".join(lines).rstrip() + "\n"
