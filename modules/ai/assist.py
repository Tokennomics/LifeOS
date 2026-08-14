"""The `/ai/*` surface — twenty endpoints that were prose, not inference.

None of them called a model. `/ai/copilot-icebreaker` returned three sentences about a
washed Ethiopian pour-over at Fabrica for whatever name you passed it. `/ai/squad-agent`
reported it had "negotiated 5 calendars" and confirmed Alex, Elena R., Marcus T. and Sophia
K. `/ai/micro-itinerary` walked everyone through the same three Lisbon venues. The word AI
was doing all the work.

Two rules shape the replacement, and the second matters more than the first:

**1. Grounding before generation.** Every function here starts by gathering what the graph
actually holds — the meetups on the board, the events published, who is open, who you have
not seen in a while — and generates only over that. A model given no facts writes plausible
venue names, which is the same failure as before with a bigger bill. So the model never
invents the *content*, only the *wording*, and every suggestion carries the record it came
from.

**2. It works with no API key.** House rule, and here it is load-bearing rather than
decorative: the ungrounded parts of these endpoints were the invented parts, so once
generation is confined to real records, the no-key path can produce the same suggestions
with plainer sentences. `assisted: false` says which one you got. Nothing degrades to a
placeholder and nothing 500s because a key is missing.

What this module will not do is score a life. `fulfillment_score: 87`,
`life_vision_score: 92`, `longevity_score` — those were the karma-98 bug wearing different
hats, and a number out of 100 about somebody's purpose is not something a graph of meetups
can know. Where an endpoint promised a score it now returns the counts it can actually
stand behind.
"""

import datetime

from substrate.graph import Graph

MODULE = "ai.assist"

MAX_SUGGESTIONS = 8
SOON_HOURS = 36


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _safely(fn, fallback):
    """One dead module must not blank a whole answer. These functions compose four or five
    other modules and are called from screens where a partial answer beats an error."""
    try:
        return fn()
    except Exception:
        return fallback


def available(claude=None) -> dict:
    """Whether wording will be generated or assembled. Configuration only, never a person."""
    on = bool(claude is not None and getattr(claude, "available", False))
    return {
        "assisted": on,
        "reason": "" if on else "ANTHROPIC_API_KEY is not set — suggestions are assembled "
                                "from your graph rather than written by a model",
    }


# ---- grounding ---------------------------------------------------------------

def grounding(graph: Graph, *, account_id: str = "", city: str = "") -> dict:
    """What is actually true right now, in one place.

    Everything below generates over this and nothing else. Kept public because the honesty
    claim is only checkable if the caller can see the same facts the wording was built from.
    """
    from modules.city import meetups, synergy
    from modules.discover import discover

    if not city and account_id:
        city = _safely(lambda: synergy.city_for(graph, account_id), "")

    meets = _safely(lambda: meetups.listing(graph, city, viewer_id=account_id).get(
        "meetups", []), []) if city else []
    events = _safely(lambda: discover.find(graph, city=city, limit=20), []) if city else []
    if isinstance(events, dict):
        events = events.get("items", [])
    mine = _safely(lambda: meetups.upcoming_for(graph, account_id), []) if account_id else []
    open_signals = _safely(lambda: synergy.mine(graph, account_id=account_id),
                           []) if account_id else []

    return {
        "city": city,
        "meetups": meets,
        "events": events or [],
        "your_plans": mine,
        "your_signals": open_signals,
        "empty": not (meets or events or mine),
    }


def _soon(items: list[dict], key: str) -> list[dict]:
    now, edge = _now(), _now() + datetime.timedelta(hours=SOON_HOURS)
    out = []
    for item in items:
        when = _parse(item.get(key, ""))
        if when is not None and now - datetime.timedelta(hours=2) <= when <= edge:
            out.append(item)
    out.sort(key=lambda i: str(i.get(key, "")))
    return out


def _write(claude, system: str, user: str, fallback):
    """Ask the model, and fall back to the assembled answer on any failure.

    A network blip, a rate limit or a refusal must not turn a working screen into a 500 —
    the assembled version was always good enough to ship, which is the point of building it
    first.
    """
    if claude is None or not getattr(claude, "available", False):
        return fallback, False
    try:
        text = claude.complete(system, user, max_tokens=700).strip()
        return (text, True) if text else (fallback, False)
    except Exception:
        return fallback, False


# ---- openers -----------------------------------------------------------------

_ICEBREAKER_SYSTEM = (
    "You write one-line opening messages between two people who have not met, for a "
    "travel app. You are given only facts that are true. Never invent a venue, a time, a "
    "shared history or a detail that is not in the facts. Three lines, each under 140 "
    "characters, no numbering, no emoji, plain and warm rather than clever."
)


def icebreakers(graph: Graph, *, account_id: str, target_account_id: str = "",
                city: str = "", claude=None) -> dict:
    """Openers for someone the matcher actually found.

    The old version wrote three lines about specialty coffee and Monsanto Crag for any name
    at all. These are built from the terms the two of you really published, so the opener
    can only reference something you both said.
    """
    from modules.city import synergy

    if not city:
        city = _safely(lambda: synergy.city_for(graph, account_id), "")
    shared, handle, their_note = [], "", ""
    if city and target_account_id:
        for signal in _safely(lambda: synergy.mine(graph, account_id=account_id), []):
            hit = _safely(lambda: synergy.find(graph, signal["city_label"] or signal["city"],
                                               signal["activity"], viewer_id=account_id,
                                               include_meetups=False), {"people": []})
            for person in hit.get("people", []):
                if person["account_id"] == target_account_id:
                    shared = person.get("shared_terms") or []
                    handle = person.get("handle", "")
                    their_note = person.get("note", "")
                    break

    if not shared:
        return {
            "target_account_id": target_account_id,
            "openers": [],
            "grounded_in": [],
            **available(claude),
            "suggestion": ("Nothing to open with yet. An opener is only worth sending when "
                           "it points at something you both actually said — publish what "
                           "you are up for and match with them first."),
        }

    topic = shared[0]
    assembled = [
        f"Hi{' ' + handle if handle else ''} — we both put down {topic}. Free later?",
        f"Saw we're both after {topic} here. Want to make a plan?",
        (f"You said \"{their_note}\" — I'm up for that too." if their_note
         else f"Same {topic} plan as me, apparently. Shall we?"),
    ]
    facts = [f"you both published: {', '.join(shared)}"]
    if their_note:
        facts.append(f"their note: {their_note}")
    if city:
        facts.append(f"city: {city}")

    text, assisted = _write(claude, _ICEBREAKER_SYSTEM, "Facts:\n- " + "\n- ".join(facts),
                            None)
    openers = [line.strip("-• ").strip() for line in (text or "").splitlines()
               if line.strip()][:3] if assisted else assembled
    return {
        "target_account_id": target_account_id,
        "handle": handle,
        "openers": openers or assembled,
        "grounded_in": facts,
        "assisted": assisted,
        "reason": "" if assisted else available(claude)["reason"],
    }


# ---- what to do tonight ------------------------------------------------------

def itinerary(graph: Graph, city: str = "", *, account_id: str = "", claude=None) -> dict:
    """A plan for the next day and a half, out of things that exist.

    Replaces three hardcoded Lisbon venues that every user in every city was routed
    through. An empty city returns an empty plan, because that is the true one.
    """
    facts = grounding(graph, account_id=account_id, city=city)
    stops = []
    for meetup in _soon(facts["meetups"], "starts_at"):
        stops.append({"when": meetup.get("starts_at", ""), "what": meetup.get("title", ""),
                      "where": meetup.get("place", ""), "kind": "meetup",
                      "going": meetup.get("going_count", 0),
                      "ref": meetup.get("meetup_id", "")})
    for event in _soon(facts["events"], "start"):
        stops.append({"when": event.get("start", ""), "what": event.get("title", ""),
                      "where": event.get("venue", "") or event.get("city", ""),
                      "kind": "event", "ref": event.get("id", "")})
    stops.sort(key=lambda s: s["when"])
    stops = stops[:MAX_SUGGESTIONS]

    return {
        "city": facts["city"],
        "stops": stops,
        "empty": not stops,
        **available(claude),
        "suggestion": "" if stops else (
            "Nothing is on in the next day and a half. Propose one thing and the board "
            "stops being empty for everybody, not just you."),
    }


def quests(graph: Graph, city: str = "", *, account_id: str = "", claude=None) -> dict:
    """Small things you could do soon. Same source as the itinerary, framed as options
    rather than a sequence — the old version generated five with invented hosts and crew
    sizes."""
    plan = itinerary(graph, city, account_id=account_id, claude=claude)
    return {
        "city": plan["city"],
        "quests": [{"title": s["what"], "when": s["when"], "where": s["where"],
                    "kind": s["kind"], "ref": s["ref"]} for s in plan["stops"]],
        "empty": plan["empty"],
        "assisted": plan["assisted"],
        "reason": plan["reason"],
        "suggestion": plan["suggestion"],
    }


# ---- the crew's plan ---------------------------------------------------------

def crew_plan(graph: Graph, crew_id: str = "", *, account_id: str = "",
              claude=None) -> dict:
    """What the crew is actually going to.

    Three endpoints claimed to do this — `squad-agent`, `agent-negotiator`,
    `group-concierge` — and all three reported a negotiation between five calendars, a
    booked table and a pre-authorised card split. There are no calendars to negotiate, no
    booking integration and no payment rail. What the app does hold is who said they are
    coming, which is the part that decides whether a plan happens.
    """
    from modules.city import meetups

    facts = grounding(graph, account_id=account_id)
    upcoming = _soon(facts["meetups"], "starts_at")
    plans = []
    for meetup in upcoming:
        plans.append({
            "meetup_id": meetup.get("meetup_id", ""), "title": meetup.get("title", ""),
            "starts_at": meetup.get("starts_at", ""), "place": meetup.get("place", ""),
            "going": meetup.get("going", []), "going_count": meetup.get("going_count", 0),
            "you_are_going": meetup.get("you_are_going", False),
        })
    return {
        "crew_id": crew_id,
        "city": facts["city"],
        "plans": plans[:MAX_SUGGESTIONS],
        "empty": not plans,
        # Stated rather than implied: nothing here books anything or moves any money.
        "not_included": ["calendar negotiation", "venue booking", "payment"],
        **available(claude),
        "suggestion": "" if plans else (
            "Nothing on the board in the next day and a half. Propose a time and place — "
            "people join plans, not intentions."),
        "safety_note": meetups.SAFETY_NOTE,
    }


# ---- people you are letting slide -------------------------------------------

def reconnect(graph: Graph, *, account_id: str = "", claude=None) -> dict:
    """Who you have not seen in a while.

    `friendship-compounding` listed three friends with invented notes and nudges. The
    reconnect module has ranked real people by contact decay since Sprint 1; this is that
    list, and nothing else.
    """
    from modules.reconnect import decay

    people = _safely(lambda: decay.ranked(graph, limit=MAX_SUGGESTIONS), [])
    return {
        "people": people,
        "empty": not people,
        **available(claude),
        "suggestion": "" if people else (
            "Nobody tracked yet. Add the people you actually want to keep up with and this "
            "starts telling you when it has been too long."),
    }


def serendipity(graph: Graph, *, account_id: str = "", claude=None) -> dict:
    """Overlaps worth acting on right now.

    The old version detected a "serendipity window" with a named friend 400 m away and a
    weather condition. There is no location sharing and no weather provider. The overlap
    this app can observe is two people who have both said they are up for the same thing in
    the same city.
    """
    from modules.city import synergy

    found = _safely(lambda: synergy.overlap(graph, viewer_id=account_id),
                    {"overlaps": [], "open_signals": 0})
    return {
        "overlaps": found.get("overlaps", []),
        "open_signals": found.get("open_signals", 0),
        "empty": not found.get("overlaps"),
        **available(claude),
        "suggestion": found.get("suggestion", ""),
    }


# ---- smaller, stated-state helpers -------------------------------------------

def quiet_options(graph: Graph, city: str = "", *, account_id: str = "",
                  max_group: int = 4, claude=None) -> dict:
    """Small things happening, for when a big night is the wrong answer.

    `empathy-vibe-tuner` claimed to *detect* an emotional state and then tuned an
    environment for it, naming a glasshouse and a companion called Isla. Nothing detects a
    mood here and nothing should pretend to — you say how you are, and this filters what is
    really on down to the plans with few enough people to be quiet.
    """
    facts = grounding(graph, account_id=account_id, city=city)
    small = [m for m in _soon(facts["meetups"], "starts_at")
             if m.get("going_count", 0) <= max_group]
    return {
        "city": facts["city"],
        "max_group": max_group,
        "options": small[:MAX_SUGGESTIONS],
        "empty": not small,
        # Stated, because the old version asserted the opposite.
        "no_mood_detection": ("Nothing here reads your mood. You said how you are; this "
                              "only filters what is already on the board."),
        **available(claude),
        "suggestion": "" if small else (
            f"Nothing on with {max_group} or fewer people. Propose something small — those "
            f"are the ones that are easiest to say yes to."),
    }


def rsvp_matches(graph: Graph, rule: str = "", *, account_id: str = "",
                 claude=None) -> dict:
    """What a standing preference would match, right now.

    `smart-autorsvp` reported `SPOT_PRE_RESERVED` for a Wednesday surf that did not exist.
    Nothing here reserves anything: joining a meetup is a public act with somebody expecting
    you, and an agent doing it silently on your behalf is not a feature. This shows the
    matches; you join them.
    """
    from modules.city import synergy

    facts = grounding(graph, account_id=account_id)
    rule = str(rule or "").strip()
    hits = []
    for meetup in _soon(facts["meetups"], "starts_at"):
        text = f"{meetup.get('title', '')} {meetup.get('note', '')}"
        shared = synergy._shared(rule, text) if rule else []
        if shared or not rule:
            hits.append({**meetup, "shared_terms": shared})
    return {
        "rule": rule,
        "city": facts["city"],
        "matches": hits[:MAX_SUGGESTIONS],
        "empty": not hits,
        "auto_joined": False,
        "why_not": ("Joining is a public act with somebody expecting you. This app will not "
                    "do that on your behalf without you tapping it."),
        **available(claude),
        "suggestion": "" if hits else (
            "Nothing coming up matches that yet. It will show here when somebody proposes "
            "one."),
    }


_TRANSLATE_SYSTEM = (
    "You explain local phrases and customs for a traveller. Answer in JSON with keys "
    "`translation` (plain English), `etiquette` (one practical sentence, or empty if you "
    "have nothing solid), and `glossary` (an object of term -> meaning for words worth "
    "knowing). If you do not know a dialect term, leave it out rather than guessing."
)

_TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "translation": {"type": "string"},
        "etiquette": {"type": "string"},
        "glossary": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["translation", "etiquette", "glossary"],
    "additionalProperties": False,
}


def translate(phrase: str, city: str = "", *, claude=None) -> dict:
    """Turn a local phrase into plain English.

    The only endpoint in this group that genuinely cannot work without a key — it was four
    Scottish words in a dict, returned for every city on earth, including the etiquette tip.
    Rather than degrade into a smaller lie it reports unavailable, exactly as the mailer
    does without a provider.
    """
    phrase = str(phrase or "").strip()
    if not phrase:
        raise ValueError("which phrase?")
    state = available(claude)
    if not state["assisted"]:
        return {"available": False, "phrase": phrase, "city": city,
                "reason": "translation needs ANTHROPIC_API_KEY; there is no offline "
                          "dictionary in this app and the one that used to be here was "
                          "four Scottish words returned for every city"}
    try:
        out = claude.complete_json(
            _TRANSLATE_SYSTEM,
            f"City: {city or 'unknown'}\nPhrase: {phrase}",
            schema=_TRANSLATE_SCHEMA, max_tokens=600)
    except Exception as exc:
        return {"available": False, "phrase": phrase, "city": city,
                "reason": f"translation failed: {exc}"}
    return {"available": True, "phrase": phrase, "city": city,
            "translation": out.get("translation", ""),
            "etiquette": out.get("etiquette", ""),
            "glossary": out.get("glossary", {})}


_PLAN_SYSTEM = (
    "You extract plans from a spoken note. Answer in JSON: `stops` is a list of "
    "{when, place, what}. Use only what the note says — if it gives no time, leave `when` "
    "empty rather than inventing one, and never add a stop that was not mentioned."
)

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "stops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"when": {"type": "string"}, "place": {"type": "string"},
                               "what": {"type": "string"}},
                "required": ["when", "place", "what"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["stops"],
    "additionalProperties": False,
}


def extract_plan(transcript: str, *, claude=None) -> dict:
    """Pull the stops out of a voice note you have already transcribed.

    Note what this does *not* claim: there is no speech-to-text here. The old endpoint
    reported `processed: True` over a transcript it had defaulted for you, then returned two
    Lisbon venues that appeared in no note at all. Bring text; this reads it.
    """
    transcript = str(transcript or "").strip()
    if not transcript:
        raise ValueError("no transcript — this reads text, it does not record audio")
    state = available(claude)
    if not state["assisted"]:
        return {"available": False, "transcript": transcript, "stops": [],
                "reason": "reading a note into stops needs ANTHROPIC_API_KEY",
                "speech_to_text": False}
    try:
        out = claude.complete_json(_PLAN_SYSTEM, transcript, schema=_PLAN_SCHEMA,
                                   max_tokens=800)
    except Exception as exc:
        return {"available": False, "transcript": transcript, "stops": [],
                "reason": f"extraction failed: {exc}", "speech_to_text": False}
    return {"available": True, "transcript": transcript,
            "stops": out.get("stops", []),
            # The stops are read, not booked. `outing_card_created: True` was not true.
            "created": False,
            "speech_to_text": False,
            "next_step": "Propose any of these as a meetup and people can join it."}


def spending(graph: Graph, *, account_id: str = "", claude=None) -> dict:
    """What outings have actually cost, from the ledger.

    `wealth-value-optimizer` returned a "fulfilment ROI" per spending category — a ratio
    between money and fulfilment, neither of which it had. The ledger does hold real splits,
    so this reports those and nothing more.
    """
    rows = _safely(lambda: _ledger_rows(graph), [])
    total = round(sum(float(r.get("amount", 0) or 0) for r in rows), 2)
    return {
        "splits": rows[:MAX_SUGGESTIONS],
        "split_count": len(rows),
        "total": total,
        "empty": not rows,
        "no_roi": ("There is no fulfilment score to divide money by, so there is no ROI "
                   "here. These are the splits you logged."),
        **available(claude),
        "suggestion": "" if rows else "Nothing logged yet — split a bill and it shows here.",
    }


def _ledger_rows(graph: Graph) -> list[dict]:
    rows = graph.session(MODULE, {"content:read"}).find_entities(
        "content", {"type": "expense_split"}, limit=200)
    out = [{"split_id": r["id"], "amount": r["attrs"].get("total_amount", 0),
            "currency": r["attrs"].get("currency", ""),
            "created_at": r["attrs"].get("created_at", "")} for r in rows]
    out.sort(key=lambda r: str(r["created_at"]), reverse=True)
    return out
