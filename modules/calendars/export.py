"""ICS iCalendar Exporter (RFC 5545).

Generates subscribable .ics feeds for personal events and crew meets.
Zero external C dependencies, pure python string formatting.
"""

from datetime import datetime, timezone
import re
from substrate.graph import Graph

SCOPES = {"events:read", "crews:read", "content:read"}


def _escape(text: str) -> str:
    if not text:
        return ""
    res = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    return res


def _format_datetime(iso_str: str) -> str:
    """Converts ISO 8601 string to iCalendar UTC timestamp YYYYMMDDTHHMMSSZ."""
    if not iso_str:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y%m%dT%H%M%SZ")

    cleaned = iso_str.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        parts = cleaned.split("-")
        return f"{parts[0]}{parts[1]}{parts[2]}T000000Z"

    try:
        iso_norm = cleaned.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y%m%dT%H%M%SZ")
    except Exception:
        dt_digits = re.sub(r"[^\d]", "", cleaned)
        if len(dt_digits) >= 14:
            return f"{dt_digits[:8]}T{dt_digits[8:14]}Z"
        elif len(dt_digits) >= 8:
            return f"{dt_digits[:8]}T000000Z"
        
        now = datetime.now(timezone.utc)
        return now.strftime("%Y%m%dT%H%M%SZ")


def generate_ics(events: list[dict], calendar_name: str = "LifeOS Calendar") -> str:
    """Converts a list of graph event dictionaries into an RFC 5545 VCALENDAR string."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LifeOS//NONSGML Calendar v1.0//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
    ]

    now_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for ev in events:
        eid = ev.get("id", "event-id")
        attrs = ev.get("attrs", {})
        title = attrs.get("title") or attrs.get("name") or "Untitled Event"
        start = attrs.get("start") or attrs.get("starts") or ev.get("created_at", "")
        end = attrs.get("end") or attrs.get("ends") or start
        place = attrs.get("place") or attrs.get("location") or ""
        desc = attrs.get("description") or attrs.get("note") or attrs.get("status") or ""

        dtstart = _format_datetime(start)
        dtend = _format_datetime(end)

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{eid}@lifeos")
        lines.append(f"DTSTAMP:{now_ts}")
        lines.append(f"DTSTART:{dtstart}")
        lines.append(f"DTEND:{dtend}")
        lines.append(f"SUMMARY:{_escape(title)}")
        if place:
            lines.append(f"LOCATION:{_escape(place)}")
        if desc:
            lines.append(f"DESCRIPTION:{_escape(desc)}")
        lines.append("STATUS:CONFIRMED")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def export_user_ics(graph: Graph, calendar_name: str = "LifeOS Personal") -> str:
    """Fetches all events accessible in the user's graph and returns an ICS string."""
    session = graph.session("calendars", SCOPES)
    events = session.find_entities("event")
    return generate_ics(events, calendar_name=calendar_name)


def export_crew_ics(graph: Graph, crew_id: str) -> str:
    """Fetches events associated with a specific crew and returns an ICS string."""
    session = graph.session("calendars", SCOPES)
    crew = session.get_entity(crew_id)
    crew_name = crew["attrs"].get("name", "Crew") if crew else "Crew"
    
    all_events = session.find_entities("event")
    crew_events = [
        ev for ev in all_events
        if ev.get("attrs", {}).get("crew_id") == crew_id or
           ev.get("attrs", {}).get("space_id") == crew_id
    ]
    # Standing routines belong in the feed too. They are a rule rather than rows, so they
    # are expanded here — this is the part that makes "synced to your calendar" true, rather
    # than the `synced_calendars: 5` the routine endpoint used to report.
    try:
        from modules.routines import squad
        crew_events = crew_events + squad.events_for_ics(graph, crew_id)
    except Exception:
        # A calendar feed that 500s because one routine is malformed is worse than one that
        # is missing a routine; the one-off meets above are the part people rely on.
        pass
    return generate_ics(crew_events, calendar_name=f"LifeOS Crew - {crew_name}")
