"""Discover — graph flow: publish public events, declare intents, get matches.

Public events are ordinary `event` entities (type="social") carrying visibility/topic/city,
so they compound with the rest of the graph instead of living in a side table. Crews already
carry visibility/topic/city, so the same matcher ranks both.
"""

import datetime

from modules.discover import core
from substrate import now_iso
from substrate.graph import Graph

SCOPES = {"events:read", "events:write", "content:read", "content:write", "interests:read"}
MODULE = "discover"


def _norm(s, cap: int = 120) -> str:
    return str(s or "").strip()[:cap]


def publish_event(graph: Graph, title: str, start: str = "", city: str = "", topic: str = "",
                  place: str = "", visibility: str = "private", crew_id: str = "",
                  source: str = MODULE) -> dict:
    """Put an event on the map. `visibility="public"` makes it discoverable by anyone
    matching on city + interest; anything else stays invisible to discovery."""
    title = _norm(title)
    if not title:
        raise ValueError("an event needs a title")
    if visibility not in ("private", "public"):
        raise ValueError("visibility must be 'private' or 'public'")
    session = graph.session(MODULE, SCOPES)
    event_id = session.create_entity("event", {
        "type": "social", "title": title, "start": _norm(start, 40), "place": _norm(place, 80),
        "city": _norm(city, 60), "topic": _norm(topic, 40), "visibility": visibility,
        "crew_id": crew_id, "busy": False, "created_at": now_iso(),
    }, source=source)
    return {"event_id": event_id, "title": title, "visibility": visibility,
            "city": _norm(city, 60), "topic": _norm(topic, 40)}


def set_intent(graph: Graph, city: str, interests=None, starts: str = "", ends: str = "",
               source: str = MODULE) -> dict:
    """"When I land in Lisbon I want sushi night" — a standing ask the matcher reads."""
    city = _norm(city, 60)
    if not city:
        raise ValueError("an intent needs a city")
    wants = [_norm(i, 40) for i in (interests or []) if _norm(i, 40)]
    session = graph.session(MODULE, SCOPES)
    intent_id = session.create_entity("content", {
        "type": "travel_intent", "city": city, "interests": wants,
        "starts": _norm(starts, 40), "ends": _norm(ends, 40), "created_at": now_iso(),
    }, source=source)
    return {"intent_id": intent_id, "city": city, "interests": wants,
            "starts": starts, "ends": ends}


def intents(graph: Graph, limit: int = 50) -> list[dict]:
    session = graph.session(MODULE, SCOPES)
    return [{"id": i["id"], "city": i["attrs"].get("city", ""),
             "interests": i["attrs"].get("interests", []),
             "starts": i["attrs"].get("starts", ""), "ends": i["attrs"].get("ends", "")}
            for i in session.find_entities("content", {"type": "travel_intent"}, limit=limit)]


def profile_interests(graph: Graph, limit: int = 100) -> list[str]:
    """Interests already in the graph — VoiceOS extracts these from your captures, so the
    matcher knows what you're into without you re-typing it."""
    session = graph.session(MODULE, SCOPES)
    return [i["attrs"].get("name", "") for i in session.find_entities("interest", limit=limit)
            if i["attrs"].get("name")]


def _event_items(session) -> list[dict]:
    out = []
    for ev in session.find_entities("event", {"type": "social"}, limit=300):
        a = ev["attrs"]
        out.append({"id": ev["id"], "kind": "event", "title": a.get("title", ""),
                    "topic": a.get("topic", ""), "city": a.get("city", ""),
                    "start": a.get("start", ""), "place": a.get("place", ""),
                    "visibility": a.get("visibility", "private"), "crew_id": a.get("crew_id", ""),
                    "going_count": len(a.get("interested", []) or [])})
    return out


def mark_interest(graph: Graph, event_id: str, person_id: str, going: bool = True,
                  source: str = MODULE) -> dict:
    """"I'm in" on a public event — the popularity signal the feed ranks with.
    Idempotent, and reversible with going=False."""
    session = graph.session(MODULE, SCOPES)
    event = session.get_entity(event_id)
    if event is None or event["kind"] != "event":
        raise ValueError("unknown event")
    interested = list(event["attrs"].get("interested", []) or [])
    if going and person_id not in interested:
        interested.append(person_id)
    elif not going and person_id in interested:
        interested.remove(person_id)
    session.update_entity(event_id, {"interested": interested}, source=source)
    return {"event_id": event_id, "going": going, "going_count": len(interested)}


def _crew_items(session) -> list[dict]:
    out = []
    for crew in session.find_entities("content", {"type": "crew"}, limit=200):
        a = crew["attrs"]
        out.append({"id": crew["id"], "kind": "crew", "title": a.get("name", ""),
                    "topic": a.get("topic", ""), "city": a.get("city", ""), "start": "",
                    "visibility": a.get("visibility", "private"),
                    "admission": a.get("admission", "approval")})
    return out


def find(graph: Graph, city: str = "", interests=None, include_past: bool = False,
         limit: int = 20, only_matches: bool = False) -> dict:
    """What's on for me here? Public events + public crews, ranked by interest match.

    With no explicit interests, your graph's own interests are used — the "match that
    profile" behaviour. `only_matches=True` narrows to things that actually hit your
    interests instead of everything local. Private items are filtered out before scoring,
    always — invisibility is not a low ranking.
    """
    session = graph.session(MODULE, SCOPES)
    wants = list(interests) if interests else profile_interests(graph)
    now = "" if include_past else datetime.datetime.now(datetime.timezone.utc).isoformat()
    floor = 0.1 if only_matches else 0.0

    events = core.rank_matches(_event_items(session), wants, city=city, now=now,
                               limit=limit, min_score=floor)
    crews_out = core.rank_matches(_crew_items(session), wants, city=city, now="",
                                  limit=limit, min_score=floor)
    return {"city": city, "interests": wants, "events": events, "crews": crews_out}


def _in_window(start: str, starts: str, ends: str) -> bool:
    """Is this event inside the trip window? Undated events always qualify."""
    if not start:
        return True
    if starts and start[:len(starts)] < starts:
        return False
    if ends and start[:len(ends)] > ends:
        return False
    return True


def feed(graph: Graph, cities=None, interests=None, limit: int = 20) -> dict:
    """One ranked stream for where you are AND where you're going to be.

    Scopes come from the cities you pass plus every stored travel intent, so a trip you
    declared last week keeps feeding you its city's events — and only within its dates.
    Ranking blends interest match, a saturating crowd signal, and how soon it is; each
    item says why it's there.
    """
    session = graph.session(MODULE, SCOPES)
    wants = list(interests) if interests else profile_interests(graph)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    scopes = [{"city": c, "starts": "", "ends": "", "label": c, "interests": wants}
              for c in (cities or []) if c]
    for intent in intents(graph):
        label = intent["city"]
        if intent.get("starts"):
            label += f" ({intent['starts']}{'–' + intent['ends'] if intent.get('ends') else ''})"
        # What you asked for in THAT city wins there — "in Lisbon I want sushi" should
        # drive the Lisbon slice of the feed even if your general profile says otherwise.
        scoped = list(dict.fromkeys((intent.get("interests") or []) + wants))
        scopes.append({"city": intent["city"], "starts": intent.get("starts", ""),
                       "ends": intent.get("ends", ""), "label": label,
                       "interests": scoped or wants})
    if not scopes:
        scopes = [{"city": "", "starts": "", "ends": "", "label": "everywhere", "interests": wants}]

    events = _event_items(session)
    best: dict[str, dict] = {}
    for scope in scopes:
        city_key = scope["city"].strip().lower()
        pool = [e for e in events
                if (not city_key or (e.get("city") or "").strip().lower() == city_key)
                and _in_window(e.get("start", ""), scope["starts"], scope["ends"])]
        for item in core.rank_feed(pool, scope["interests"], now=now, limit=limit):
            item = {**item, "where": scope["label"]}
            if scope["city"]:
                item["reasons"] = item["reasons"] + [f"while you're in {scope['label']}"]
            keep = best.get(item["id"])
            if keep is None or item["score"] > keep["score"]:
                best[item["id"]] = item

    ranked = sorted(best.values(),
                    key=lambda i: (-i["score"], i.get("start") or "9999", i.get("title", "")))
    return {"interests": wants, "scopes": [s["label"] for s in scopes],
            "items": ranked[:max(0, limit)]}


def find_for_intent(graph: Graph, intent_id: str, limit: int = 20) -> dict:
    session = graph.session(MODULE, SCOPES)
    intent = session.get_entity(intent_id)
    if intent is None or intent["attrs"].get("type") != "travel_intent":
        raise ValueError("unknown intent")
    a = intent["attrs"]
    result = find(graph, city=a.get("city", ""), interests=a.get("interests") or None, limit=limit)
    result["intent_id"] = intent_id
    return result
