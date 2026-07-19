"""Calendar free/busy ingest -> busy event entities in the graph.

v0.1 source: a secret ICS URL (Google Calendar: Settings -> your calendar ->
"Secret address in iCal format"). Zero OAuth, works for any calendar provider.
Privacy default (risk register #5): free/busy only — titles are NOT stored unless
calendar.store_titles is true.

CLI:  python -m modules.calendars.freebusy [--config path]
"""

import argparse
import datetime
import json

from substrate.graph import Graph

SCOPES = {"events:read", "events:write"}
WINDOW_DAYS = 14

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def parse_ics(text: str, default_tz: str = "UTC") -> list[dict]:
    """Minimal ICS parser: VEVENT uid/start/end/title. Handles folded lines, UTC 'Z',
    TZID params, and all-day VALUE=DATE events."""
    raw = text.replace("\r\n", "\n").split("\n")
    lines: list[str] = []
    for line in raw:  # unfold RFC 5545 continuation lines
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)

    events, current = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current and "start" in current and "end" in current:
                current.setdefault("uid", f"noduid-{current['start']}")
                current.setdefault("title", "")
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *params = head.split(";")
        if name == "UID":
            current["uid"] = value.strip()
        elif name == "SUMMARY":
            current["title"] = value.strip()
        elif name in ("DTSTART", "DTEND"):
            dt = _parse_dt(value.strip(), params, default_tz)
            if dt is not None:
                current["start" if name == "DTSTART" else "end"] = dt.isoformat()
    return events


def _parse_dt(value: str, params: list[str], default_tz: str):
    tz = _tz(default_tz)
    for p in params:
        if p.startswith("TZID="):
            tz = _tz(p[5:], fallback=tz)
    try:
        if "VALUE=DATE" in params or (len(value) == 8 and value.isdigit()):
            return datetime.datetime.strptime(value, "%Y%m%d").replace(tzinfo=tz)
        if value.endswith("Z"):
            return datetime.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
    except ValueError:
        return None


def _tz(name: str, fallback=datetime.timezone.utc):
    if ZoneInfo is None or not name:
        return fallback
    try:
        return ZoneInfo(name)
    except Exception:
        return fallback


def sync(graph: Graph, cfg: dict, ics_text: str | None = None, now: datetime.datetime | None = None) -> dict:
    """Fetch (or take) ICS, upsert busy events within [now-1d, now+WINDOW_DAYS]."""
    cal = cfg.get("calendar", {})
    store_titles = bool(cal.get("store_titles"))
    tzname = cfg.get("owner", {}).get("timezone", "UTC")

    if ics_text is None:
        url = cal.get("ics_url", "")
        if not url:
            return {"status": "not-configured", "events": 0}
        import httpx

        ics_text = httpx.get(url, timeout=30, follow_redirects=True).raise_for_status().text

    now = now or datetime.datetime.now(datetime.timezone.utc)
    lo, hi = now - datetime.timedelta(days=1), now + datetime.timedelta(days=WINDOW_DAYS)
    session = graph.session("calendars", SCOPES)
    written = 0
    for ev in parse_ics(ics_text, default_tz=tzname):
        start = datetime.datetime.fromisoformat(ev["start"])
        if not (lo <= start <= hi):
            continue
        attrs = {"uid": ev["uid"], "start": ev["start"], "end": ev["end"], "busy": True, "source": "ics"}
        if store_titles:
            attrs["title"] = ev["title"]
        existing = session.find_entities("event", {"uid": ev["uid"]}, limit=1)
        if existing:
            session.update_entity(existing[0]["id"], attrs, source="ics-sync")
        else:
            session.create_entity("event", attrs, source="ics-sync")
        written += 1
    return {"status": "ok", "events": written}


def main():
    from substrate import load_config
    from substrate.migrate import migrate

    parser = argparse.ArgumentParser(description="Calendar free/busy ingest")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    graph = Graph(migrate(cfg), default_owner=cfg.get("owner", {}).get("id"))
    print(json.dumps(sync(graph, cfg)))


if __name__ == "__main__":
    main()
