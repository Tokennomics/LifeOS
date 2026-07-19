"""Convoy — crew assembly v1: invite people you already know, track RSVPs, log attendance.

Attendance is where the graph compounds: marking attended bumps every yes-person's
last_contact (Reconnect reads it) and publishes event.attended (Memento quests read it).
"""

import datetime

from modules.convoy.events_ingest import SCOPES
from substrate.graph import Graph

INVITE_SYSTEM = (
    "You draft one short group message inviting friends to a specific event. Casual, "
    "concrete (event, when, where), zero pressure, one clear ask ('who's in?'). "
    "Under 50 words. Return only the message text."
)


def _get_social_event(session, event_id: str) -> dict:
    event = session.get_entity(event_id)
    if event is None or event["kind"] != "event" or event["attrs"].get("type") != "social":
        raise ValueError("unknown social event")
    return event


def invite(graph: Graph, event_id: str, person_ids: list[str], claude=None,
           source: str = "convoy") -> dict:
    session = graph.session("convoy", SCOPES)
    event = _get_social_event(session, event_id)
    names = []
    for pid in person_ids:
        person = session.get_entity(pid)
        if person and person["kind"] == "person":
            names.append(person["attrs"].get("name", "?"))
    invited = sorted(set(event["attrs"].get("invited", []) + person_ids))
    session.update_entity(event_id, {"invited": invited, "status": "inviting"}, source=source)

    title, start, place = (event["attrs"].get(k, "") for k in ("title", "start", "place"))
    if claude is not None and claude.available:
        text = claude.complete(
            INVITE_SYSTEM,
            f"Event: {title} at {place or 'TBC'}, {start}. Friends: {', '.join(names)}.",
            max_tokens=512,
        ).strip()
        method = "claude"
    else:
        when = start[:16].replace("T", " ")
        text = (f"Crew — {title}{f' at {place}' if place else ''} on {when}. "
                f"I'm going. Who's in?")
        method = "offline"
    return {"event_id": event_id, "invited": len(invited), "names": names, "text": text, "method": method}


def rsvp(graph: Graph, event_id: str, person_id: str, going: bool, source: str = "convoy") -> dict:
    session = graph.session("convoy", SCOPES)
    event = _get_social_event(session, event_id)
    yes = set(event["attrs"].get("yes", []))
    no = set(event["attrs"].get("no", []))
    (yes if going else no).add(person_id)
    (no if going else yes).discard(person_id)
    session.update_entity(event_id, {"yes": sorted(yes), "no": sorted(no)}, source=source)
    if going:
        session.create_edge(event_id, person_id, "with", source=source)
    return {"yes": len(yes), "no": len(no)}


def attended(graph: Graph, event_id: str, source: str = "convoy") -> dict:
    session = graph.session("convoy", SCOPES)
    event = _get_social_event(session, event_id)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    session.update_entity(event_id, {"status": "attended", "attended_at": now}, source=source)
    touched = 0
    for pid in event["attrs"].get("yes", []):
        if session.get_entity(pid):
            session.update_entity(pid, {"last_contact": now}, source=source)
            touched += 1
    graph.bus.publish("event.attended", {"event_id": event_id, "people": touched, "module": "convoy"})
    return {"event_id": event_id, "people_touched": touched}
