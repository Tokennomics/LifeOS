"""Synergy — "I want to do this, who else does?"

Eleven endpoints used to answer that question, and all eleven answered it the same way:
with Elena R., Marcus T., Sophia K. and a match score in the nineties. None of those people
exist. The feature is right — finding the one other person in a city who also wants to
boulder at six is the whole point of the app — so this replaces the invented answer, not
the question.

The honest version needs one thing the app did not have: **a way to say what you are up
for.** `city.arrival` publishes *that* you are in a city; `discover.set_intent` records what
you like but keeps it in your own slice, where nobody can match against it. Neither answers
"free for coffee in the next two hours". So this module adds a signal:

- **Public and deliberate.** Same rule as arrival — reading does not publish you, only
  `open_to` does. A signal says what you want to do and roughly when, never where you are.
- **Short-lived by design.** Availability is a statement about the next few hours, not a
  profile field. `DEFAULT_HOURS`, capped at `MAX_HOURS`, and it expires on its own so a
  stale signal never sends somebody to meet a person who went home two days ago.
- **Muted people stay muted**, exactly as in the room and in `around`.

Matching itself is deliberately explainable. There is no percentage, because there is no
honest way to compute one from two lines of free text, and a number in the nineties is
exactly what made the old version feel like a product and behave like a screensaver. A match
reports **the terms you actually share**, and the caller can see why it fired.

Two shapes of match, because two real things are being asked:

- **Same-thing** (`find`): you want bouldering, they want bouldering. Sports, dining, surf,
  raves, co-working — every activity endpoint.
- **Complementary** (`swap`): you speak English and want Portuguese; the match is somebody
  who speaks Portuguese and wants English. Matching those two on the shared word "English"
  would pair two learners who cannot help each other.

When nothing matches — which is the normal case in a young city, not an error — the answer
is `matched: false` plus the thing that would fix it, because "no results" with no next step
is how the empty city stays empty.
"""

import datetime
import re

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat

MODULE = "city.synergy"
SCOPES = {"content:read", "content:write"}
RECORD = "synergy_signal"

DEFAULT_HOURS = 4
MAX_HOURS = 48
MAX_ACTIVITY = 80
MAX_NOTE = 140
MAX_RESULTS = 25

# Words that two signals sharing them have nothing in common. Without this, "looking for
# people to surf with" and "looking for people to ski with" match on four words.
_STOPWORDS = {
    "a", "an", "and", "any", "anyone", "are", "around", "at", "be", "down", "for", "free",
    "from", "going", "hey", "hi", "in", "into", "is", "it", "join", "later", "like",
    "looking", "me", "meet", "my", "near", "of", "on", "or", "out", "people", "please",
    "someone", "somebody", "the", "to", "tonight", "up", "want", "wants", "with", "who",
    "would", "you", "your",
}


class SynergyError(ValueError):
    """A signal that cannot be published, or a search that cannot be run."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _live(row: dict, now) -> bool:
    if row["attrs"].get("withdrawn"):
        return False
    expires = _parse(row["attrs"].get("expires_at"))
    return expires is not None and expires > now


def terms(text: str) -> set[str]:
    """The words in a phrase that could meaningfully be shared with another phrase.

    Lowercased, punctuation dropped, stopwords removed, one-character tokens removed. Kept
    public because the matcher's whole claim is that you can see why it fired, and that is
    only checkable if the tokenisation is inspectable.
    """
    words = re.findall(r"[a-z0-9']+", str(text or "").lower())
    return {w for w in words if len(w) > 1 and w not in _STOPWORDS}


def _shared(a: str, b: str) -> list[str]:
    """Terms two phrases have in common, plus the substring case.

    `bouldering` and `boulder` share no token but are plainly the same activity, so a token
    on one side that begins the other counts. `ski` matching `skiing` is the same case and
    the reason a plain set intersection is not enough.
    """
    left, right = terms(a), terms(b)
    hits = set(left & right)
    for one in left:
        for other in right:
            if one != other and (one.startswith(other) or other.startswith(one)):
                hits.add(min(one, other, key=len))
    return sorted(hits)


def open_to(graph: Graph, city: str, activity: str, *, account_id: str, handle: str = "",
            note: str = "", hours: int = DEFAULT_HOURS, category: str = "",
            offers: str = "", wants: str = "", source: str = MODULE) -> dict:
    """Publish "I am up for this, in this city, for the next few hours".

    Re-opening the same activity in the same city replaces the previous signal rather than
    stacking, so somebody who edits their note does not appear in the list twice.
    """
    # Validated before slugging: `chat.slug("")` raises a ChatError, and a caller catching
    # SynergyError would miss it.
    if not str(city or "").strip():
        raise SynergyError("which city?")
    room = chat.slug(city)
    if not account_id:
        raise SynergyError("sign in first")
    activity = str(activity or "").strip()[:MAX_ACTIVITY]
    offers = str(offers or "").strip()[:MAX_ACTIVITY]
    wants = str(wants or "").strip()[:MAX_ACTIVITY]
    if not activity and not (offers or wants):
        raise SynergyError("up for what?")

    if hours is None:
        hours = DEFAULT_HOURS
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        raise SynergyError("hours must be a number")
    if hours < 1 or hours > MAX_HOURS:
        raise SynergyError(f"pick between 1 and {MAX_HOURS} hours")

    session = _sys(graph)
    key = (activity or f"{offers}>{wants}").lower()
    for row in session.find_entities(
            "content", {"type": RECORD, "city": room, "account_id": account_id}, limit=50):
        if str(row["attrs"].get("activity", "")).lower() == key or \
                str(row["attrs"].get("key", "")) == key:
            session.update_entity(row["id"], {"withdrawn": True}, source=source)

    signal_id = session.create_entity("content", {
        "type": RECORD, "city": room, "city_label": str(city or "").strip()[:80],
        "account_id": account_id, "handle": str(handle or "")[:80],
        "activity": activity, "key": key, "category": str(category or "").strip()[:80],
        "offers": offers, "wants": wants,
        "note": str(note or "").strip()[:MAX_NOTE],
        "created_at": now_iso(),
        "expires_at": (_now() + datetime.timedelta(hours=hours)).isoformat(),
        "withdrawn": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"open": True, "signal_id": signal_id, "city": room,
            "activity": activity or f"{offers} for {wants}", "hours": hours}


def close(graph: Graph, city: str, activity: str = "", *, account_id: str,
          source: str = MODULE) -> dict:
    """Take a signal down. No activity given takes down every signal in that city."""
    room = chat.slug(city)
    session = _sys(graph)
    wanted = str(activity or "").strip().lower()
    closed = 0
    for row in session.find_entities(
            "content", {"type": RECORD, "city": room, "account_id": account_id}, limit=100):
        if row["attrs"].get("withdrawn"):
            continue
        if wanted and str(row["attrs"].get("activity", "")).lower() != wanted:
            continue
        session.update_entity(row["id"], {"withdrawn": True}, source=source)
        closed += 1
    return {"closed": closed, "city": room}


def _signals(graph: Graph, room: str, *, now=None) -> list[dict]:
    now = now or _now()
    return [row for row in _sys(graph).find_entities(
        "content", {"type": RECORD, "city": room}, limit=500) if _live(row, now)]


def mine(graph: Graph, *, account_id: str, limit: int = MAX_RESULTS) -> list[dict]:
    """Every signal you currently have up, in any city — so you can see what you are
    publishing about yourself without visiting each room to check."""
    if not account_id:
        return []
    now = _now()
    out = []
    for row in _sys(graph).find_entities("content", {"type": RECORD}, limit=1000):
        if not _live(row, now) or row["attrs"].get("account_id") != account_id:
            continue
        attrs = row["attrs"]
        out.append({
            "signal_id": row["id"], "city": attrs.get("city", ""),
            "city_label": attrs.get("city_label", ""),
            "activity": attrs.get("activity", ""), "category": attrs.get("category", ""),
            "note": attrs.get("note", ""), "expires_at": attrs.get("expires_at", ""),
        })
    out.sort(key=lambda s: s["expires_at"])
    return out[:limit]


def city_for(graph: Graph, account_id: str) -> str:
    """Where the caller most recently said they are.

    So an activity search does not need the city spelled out every time: someone who
    announced Lisbon on arrival is asking about Lisbon. Returns "" when they have not
    announced anywhere, and the caller must then ask.
    """
    from modules.city import arrival

    if not account_id:
        return ""
    now = _now()
    best, best_at = "", ""
    for row in Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(
            MODULE, SCOPES).find_entities("content", {"type": arrival.RECORD}, limit=500):
        attrs = row["attrs"]
        if attrs.get("account_id") != account_id or not arrival._live(row, now):
            continue
        made = str(attrs.get("created_at", ""))
        if made >= best_at:
            best, best_at = attrs.get("city", ""), made
    return best


def _person(row: dict, why: list[str]) -> dict:
    attrs = row["attrs"]
    return {
        "account_id": attrs.get("account_id", ""),
        "handle": attrs.get("handle") or "someone",
        "activity": attrs.get("activity", ""),
        "note": attrs.get("note", ""),
        "offers": attrs.get("offers", ""),
        "wants": attrs.get("wants", ""),
        "open_until": attrs.get("expires_at", ""),
        # The replacement for the 96% score: the words this actually matched on.
        "shared_terms": why,
    }


def _meetups_for(graph: Graph, room: str, activity: str, viewer_id: str,
                 limit: int = 5) -> list[dict]:
    """Plans already on the board that fit. Somebody who wants to climb should be shown the
    climbing meetup three people are already going to before being shown a stranger."""
    from modules.city import meetups

    try:
        listed = meetups.listing(graph, room, viewer_id=viewer_id).get("meetups", [])
    except Exception:
        return []
    out = []
    for meetup in listed:
        hits = _shared(activity, f"{meetup.get('title', '')} {meetup.get('note', '')}")
        if hits or not activity:
            out.append({**meetup, "shared_terms": hits})
    return out[:limit]


def _events_for(graph: Graph, city_label: str, activity: str, limit: int = 5) -> list[dict]:
    from modules.discover import discover

    try:
        found = discover.find(graph, city=city_label, limit=25)
    except Exception:
        return []
    if isinstance(found, dict):
        found = found.get("items", [])
    out = []
    for item in found or []:
        text = f"{item.get('title', '')} {item.get('topic', '')}"
        hits = _shared(activity, text)
        if hits:
            out.append({**item, "shared_terms": hits})
    return out[:limit]


def _suggestion(matched: bool, you_are_open: bool, activity: str, city_label: str) -> str:
    if matched:
        return ""
    if not you_are_open:
        return (f"Nobody has said they are up for {activity} in {city_label} right now. "
                f"Say you are, and the next person who looks will find you.")
    return (f"You are the only one up for {activity} in {city_label} so far. "
            f"Propose a time and place — a meetup on the board is easier to join than a "
            f"stranger is to message.")


def find(graph: Graph, city: str, activity: str, *, viewer_id: str = "",
         category: str = "", limit: int = MAX_RESULTS, include_meetups: bool = True) -> dict:
    """Who else in this city is up for the same thing.

    Never returns the caller. Never returns somebody they muted. Returns an empty list
    rather than a plausible stranger when the city is empty, because the empty list is the
    true answer and the stranger is the bug this module exists to remove.
    """
    if not str(city or "").strip():
        raise SynergyError("which city?")
    room = chat.slug(city)
    label = str(city or "").strip() or room
    activity = str(activity or "").strip()

    hidden = chat.muted_by(graph, viewer_id)
    people, you_are_open = [], False
    for row in _signals(graph, room):
        attrs = row["attrs"]
        who = attrs.get("account_id", "")
        if who == viewer_id:
            if not activity or _shared(activity, attrs.get("activity", "")):
                you_are_open = True
            continue
        if who in hidden:
            continue
        hits = _shared(activity, f"{attrs.get('activity', '')} {attrs.get('note', '')}")
        if activity and not hits:
            continue
        people.append(_person(row, hits))

    people.sort(key=lambda p: (-len(p["shared_terms"]), p["open_until"]))
    people = people[:limit]

    meets = _meetups_for(graph, room, activity, viewer_id) if include_meetups else []
    events = _events_for(graph, label, activity) if include_meetups else []
    matched = bool(people or meets or events)

    return {
        "matched": matched,
        "city": room,
        "city_label": label,
        "activity": activity,
        "category": category,
        "people": people,
        "people_count": len(people),
        "meetups": meets,
        "events": events,
        "you_are_open": you_are_open,
        "suggestion": _suggestion(matched, you_are_open, activity or "this", label),
        "safety_note": _SAFETY,
    }


_SAFETY = "Meet somewhere public the first time, and tell someone where you are going."


def swap(graph: Graph, city: str, *, speak: str, learn: str, viewer_id: str = "",
         limit: int = MAX_RESULTS) -> dict:
    """Complementary matching: what you offer against what they want, both ways.

    A language exchange only works if the pairing is a mirror. Matching on shared words
    would pair two people learning the same language, who between them can teach nobody.
    """
    if not str(city or "").strip():
        raise SynergyError("which city?")
    room = chat.slug(city)
    label = str(city or "").strip() or room
    speak, learn = str(speak or "").strip(), str(learn or "").strip()
    if not (speak and learn):
        raise SynergyError("what do you speak, and what do you want to learn?")

    hidden = chat.muted_by(graph, viewer_id)
    people, you_are_open = [], False
    for row in _signals(graph, room):
        attrs = row["attrs"]
        who = attrs.get("account_id", "")
        if not (attrs.get("offers") or attrs.get("wants")):
            continue
        if who == viewer_id:
            you_are_open = True
            continue
        if who in hidden:
            continue
        they_teach = _shared(learn, attrs.get("offers", ""))
        they_learn = _shared(speak, attrs.get("wants", ""))
        if not (they_teach and they_learn):
            continue
        people.append(_person(row, sorted(set(they_teach) | set(they_learn))))

    people.sort(key=lambda p: (-len(p["shared_terms"]), p["open_until"]))
    people = people[:limit]
    matched = bool(people)
    return {
        "matched": matched, "city": room, "city_label": label,
        "speak": speak, "learn": learn, "category": "Language Exchange",
        "people": people, "people_count": len(people),
        "you_are_open": you_are_open,
        "suggestion": "" if matched else (
            f"No {learn} speaker learning {speak} is open in {label} right now. "
            f"Publish yours — the match is made by whoever looks next."),
        "safety_note": _SAFETY,
    }


def overlap(graph: Graph, *, viewer_id: str, limit: int = MAX_RESULTS) -> dict:
    """Everything your own open signals currently match, across the cities you are in.

    The old version listed two friends who were free on Friday. It had no calendars, no
    friends and no Friday — it was a literal. This is the same idea with the only overlap
    the app can actually observe: two people who have both said, right now, that they are
    up for the same thing in the same city.
    """
    signals = mine(graph, account_id=viewer_id)
    out = []
    for signal in signals:
        hit = find(graph, signal["city_label"] or signal["city"], signal["activity"],
                   viewer_id=viewer_id, category=signal.get("category", ""),
                   include_meetups=False)
        if hit["people"]:
            out.append({"activity": signal["activity"], "city": hit["city"],
                        "city_label": hit["city_label"], "people": hit["people"],
                        "open_until": signal["expires_at"]})
    return {
        "overlaps": out[:limit],
        "open_signals": len(signals),
        "suggestion": "" if out else (
            "Say what you are up for in a city and this fills in as other people do."
            if not signals else
            "Nothing overlaps yet. Your signals are up — they expire, so re-open them "
            "when you are actually free."),
    }
