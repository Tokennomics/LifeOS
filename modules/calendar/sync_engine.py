"""Multi-Calendar Sync Importer.

Bi-directional sync importer parsing external iCalendar (.ics) feed content
(Google Calendar, Outlook, Apple Calendar) into LifeOS event entities.
"""

import re
from substrate.graph import Graph

SCOPES = {"events:read", "events:write"}
MODULE = "calendar"


def import_ics_feed(graph: Graph, ics_content: str, source: str = MODULE) -> dict:
    """Parses iCalendar .ics content and imports event entities into the graph."""
    if not ics_content.strip():
        raise ValueError("ics_content required")

    session = graph.session(MODULE, SCOPES)

    # Extract VEVENT blocks
    vevent_blocks = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics_content, re.DOTALL)

    imported_events = []
    for block in vevent_blocks:
        summary_m = re.search(r"SUMMARY:(.*)", block)
        dtstart_m = re.search(r"DTSTART.*:(.*)", block)
        location_m = re.search(r"LOCATION:(.*)", block)

        title = summary_m.group(1).strip() if summary_m else "External Event"
        start_time = dtstart_m.group(1).strip() if dtstart_m else ""
        location = location_m.group(1).strip() if location_m else ""

        eid = session.create_entity(
            "event",
            {
                "title": title,
                "start_time": start_time,
                "location": location,
                "imported_from_ics": True,
            },
            source=source,
        )
        imported_events.append({"event_id": eid, "title": title, "start_time": start_time, "location": location})

    return {
        "imported_count": len(imported_events),
        "events": imported_events,
    }
