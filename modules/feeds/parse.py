"""Venue feeds — the pure part: turn one ICS or RSS/Atom document into event items.

No network, no graph. `parse_feed(text)` sniffs the format and returns a common shape so
the ingest above it never has to care which kind it got.

**ICS is the workhorse; RSS is best-effort, and the difference is not cosmetic.** An ICS
`VEVENT` states when the event is, in a field designed to say so. RSS is a *publishing*
format: its one date field, `pubDate`, is when the listing was posted. Those are not the
same fact and a feed reader that conflates them produces a calendar of announcement dates.

So **`pubDate` is never used as an event date here.** An RSS item with no determinable start
is dropped. That is a deliberate, load-bearing refusal: "Warehouse party" filed under the
Tuesday it was announced is worse than absent, because the weekend digest would show it
confidently on the wrong day and the reader has no way to tell. Dropping it is visible in
the sync report (`skipped_no_date`); a wrong date is invisible forever.

What we *will* accept as a start, in order: an explicit event-start element from one of the
common RSS event extensions, then an unambiguous ISO timestamp found anywhere in the item.
Only ISO — `08/07/2026` is the 8th of July to half the world and the 7th of August to the
other half, and a listing aggregator that guesses wrong is exactly the thing this module
must not become.
"""

import re
import xml.etree.ElementTree as ET

from modules.calendars.freebusy import parse_ics

# Element names various feeds use for a real event start. Matched on the local name, so a
# namespace prefix (ev:, event:, schema:) does not need enumerating.
START_TAGS = ("startdate", "start", "starttime", "startdatetime", "dtstart", "eventdate")
END_TAGS = ("enddate", "end", "endtime", "enddatetime", "dtend")
PLACE_TAGS = ("location", "venue", "place")

ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?\b")

MAX_TITLE = 120
MAX_PLACE = 80


def _clean(value, cap: int = MAX_TITLE) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))          # listings are full of markup
    return re.sub(r"\s+", " ", text).strip()[:cap]


def looks_like_ics(text: str) -> bool:
    return "BEGIN:VCALENDAR" in (text or "") or "BEGIN:VEVENT" in (text or "")


def parse_feed(text: str, default_tz: str = "UTC") -> list[dict]:
    """One document -> event items. Unparseable input is an empty list, never an exception:
    a venue that serves an error page must not take the whole sync down with it."""
    if not str(text or "").strip():
        return []
    if looks_like_ics(text):
        return parse_ics_events(text, default_tz)
    return parse_rss(text)


def parse_ics_events(text: str, default_tz: str = "UTC") -> list[dict]:
    out = []
    for ev in parse_ics(text, default_tz=default_tz):
        if not ev.get("start"):
            continue
        out.append({"uid": ev.get("uid", ""), "title": _clean(ev.get("title")),
                    "start": ev["start"], "end": ev.get("end", ""),
                    "place": _clean(ev.get("place"), MAX_PLACE),
                    "url": _clean(ev.get("url"), 300), "format": "ics"})
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first(node, names) -> str:
    for child in node.iter():
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text.strip()
    return ""


def _iso_in(*values) -> str:
    for value in values:
        found, _ = _iso_match(value)
        if found:
            return found
    return ""


def _iso_match(value) -> tuple[str, str]:
    """The timestamp found, and the text with it removed.

    Feeds that carry the date in the title (`Late tour 2026-08-09T21:00`) are common, and
    lifting the date out without taking it *off* the title leaves the raw ISO string sitting
    in the digest — which reads like a machine wrote it, because one did.
    """
    text = str(value or "")
    match = ISO.search(text)
    if not match:
        return "", text
    date, time = match.group(1), match.group(2)
    stamp = f"{date}T{time}" if time else date
    return stamp, _tidy(text[:match.start()] + " " + text[match.end():])


SEPARATORS = r"[\s,;:|/–—-]+"


def _tidy(text: str) -> str:
    """Close the gap the date left, including whichever separator it was hanging off.

    Both ends: a leading date ("2026-08-09: Late tour") strands the colon just as a trailing
    one strands the dash.
    """
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(f"^{SEPARATORS}", "", text)
    return re.sub(f"{SEPARATORS}$", "", text).strip()


def parse_rss(text: str) -> list[dict]:
    try:
        root = ET.fromstring(str(text or "").strip())
    except ET.ParseError:
        return []

    out = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = _clean(_first(node, ("title",)))
        description = _first(node, ("description", "summary", "content"))
        # Atom's <link href="..."/> carries no text, so the text search would fall through
        # to <id> — which is a tag: URN, not something a reader can open.
        link = _link_href(node) or _first(node, ("link", "guid", "id"))

        # Explicit element first; only then the text. Never pubDate — see the module docstring.
        start = _iso_in(_first(node, START_TAGS))
        if not start:
            start, title = _iso_match(title)          # and take the date off the title
        if not start:
            start = _iso_in(description)
        if not start:
            out.append({"uid": _clean(link or title, 300), "title": title, "start": "",
                        "end": "", "place": "", "url": _clean(link, 300), "format": "rss",
                        "skipped": "no_date"})
            continue

        out.append({"uid": _clean(link or f"{title}:{start}", 300), "title": title,
                    "start": start, "end": _iso_in(_first(node, END_TAGS)),
                    "place": _clean(_first(node, PLACE_TAGS), MAX_PLACE),
                    "url": _clean(link, 300), "format": "rss"})
    return out


def _link_href(node) -> str:
    """Atom puts the link in an attribute, not in the element text."""
    for child in node.iter():
        if _local(child.tag) == "link" and child.get("href"):
            return child.get("href")
    return ""
