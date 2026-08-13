"""Arrival — the app's first thirty seconds in a new city.

A new instance shows a signed-in user an empty week, an empty feed and an empty crew
directory. That is the honest state of the data and it is also the moment most people close
the app for good. This module answers one question — *I just landed in Lisbon, what is here?*
— by composing things that already exist rather than inventing another store: the city room,
the public crew directory, published events, subscribed venue feeds.

It adds exactly one new thing, because listings alone do not introduce anybody: **an
explicit, expiring "I'm around" marker.**

`discover.set_intent` already records "when I land in Lisbon I want sushi night", but it is
owner-scoped and therefore private — the same shape as the bug that made every dating match
`is_mutual: False`. A standing wish nobody can see connects nobody. So an announcement here
is a deliberately *public* act, and it is built accordingly:

- **Opt-in per city, and never implied.** Reading the room does not announce you; posting
  does not announce you. You say it or it does not happen. Announcing that you are in a city
  is a much larger disclosure than saying one thing in a chat — it is structured, durable and
  answers "is this person here right now", which is the question a stalker asks.
- **It expires** (`DEFAULT_DAYS`, capped at `MAX_DAYS`), and you can withdraw it instantly.
- **City only.** No coordinates, no venue, no "online now" — the granularity is the thing
  that makes this safe, and a finer one is not a feature request to accept casually.
- **The chat mute list applies here too.** Somebody you muted in the room should not reappear
  in a list of people to meet.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat

MODULE = "city.arrival"
SCOPES = {"content:read", "content:write"}
RECORD = "city_presence"

DEFAULT_DAYS = 3
MAX_DAYS = 14
MAX_NOTE = 140
MAX_AROUND = 50


class ArrivalError(ValueError):
    """An announcement that cannot be made."""


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


def announce(graph: Graph, city: str, *, account_id: str, handle: str = "", note: str = "",
             days: int = DEFAULT_DAYS, source: str = MODULE) -> dict:
    """Say you are in a city and open to meeting people, until a date.

    Re-announcing the same city replaces the previous marker rather than stacking, so a
    list of people around never shows the same person three times because they updated
    their note.
    """
    room = chat.slug(city)
    if not account_id:
        raise ArrivalError("sign in first")
    # `days or DEFAULT_DAYS` silently turned 0 into 3 — quietly publishing a presence the
    # caller explicitly asked not to create. A missing value takes the default; a value
    # that is present and wrong is refused.
    if days is None:
        days = DEFAULT_DAYS
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ArrivalError("days must be a number")
    if days < 1 or days > MAX_DAYS:
        raise ArrivalError(f"pick between 1 and {MAX_DAYS} days")

    session = _sys(graph)
    for row in session.find_entities(
            "content", {"type": RECORD, "city": room, "account_id": account_id}, limit=10):
        session.update_entity(row["id"], {"withdrawn": True}, source=source)

    presence_id = session.create_entity("content", {
        "type": RECORD, "city": room, "city_label": str(city or "").strip()[:80],
        "account_id": account_id, "handle": str(handle or "")[:80],
        "note": str(note or "").strip()[:MAX_NOTE],
        "created_at": now_iso(),
        "expires_at": (_now() + datetime.timedelta(days=days)).isoformat(),
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"announced": True, "city": room, "days": days, "presence_id": presence_id}


def withdraw(graph: Graph, city: str, *, account_id: str, source: str = MODULE) -> dict:
    """Take it back. Immediate, and needs no reason."""
    room = chat.slug(city)
    session = _sys(graph)
    removed = 0
    for row in session.find_entities(
            "content", {"type": RECORD, "city": room, "account_id": account_id}, limit=10):
        if not row["attrs"].get("withdrawn"):
            session.update_entity(row["id"], {"withdrawn": True}, source=source)
            removed += 1
    return {"withdrawn": True, "city": room, "removed": removed}


def around(graph: Graph, city: str, *, viewer_id: str = "", limit: int = MAX_AROUND) -> list[dict]:
    """Who else has said they are here. Handles and notes only — never an account's email,
    never a location finer than the city."""
    room = chat.slug(city)
    now = _now()
    hidden = chat.muted_by(graph, viewer_id)

    out = []
    for row in _sys(graph).find_entities("content", {"type": RECORD, "city": room},
                                         limit=MAX_AROUND * 4):
        if not _live(row, now):
            continue
        attrs = row["attrs"]
        if attrs.get("account_id") in hidden:
            continue
        out.append({
            "account_id": attrs.get("account_id", ""),
            "handle": attrs.get("handle") or "someone",
            "note": attrs.get("note", ""),
            "since": attrs.get("created_at", ""),
            "mine": attrs.get("account_id") == viewer_id,
        })
    out.sort(key=lambda p: p["since"], reverse=True)
    return out[:limit]


def _my_presence(graph: Graph, city: str, account_id: str) -> dict | None:
    for person in around(graph, city, viewer_id=account_id):
        if person["mine"]:
            return person
    return None


def arrival(graph: Graph, city: str, *, viewer_id: str = "") -> dict:
    """Everything worth knowing about a city in one call.

    Deliberately one request: this is the screen someone sees ten seconds after signing in,
    and six round trips on hotel wifi is the difference between a product and a spinner.
    Every part degrades on its own — a module that raises must not blank the whole screen,
    because an empty city is the normal case on a young instance, not an error.
    """
    room = chat.slug(city)
    label = str(city or "").strip() or room

    def safely(fn, fallback):
        try:
            return fn()
        except Exception:
            return fallback

    from modules.crews import crews
    from modules.discover import discover
    from modules.feeds import ingest

    crew_list = safely(lambda: crews.directory(graph, city=label, limit=10), [])
    events = safely(lambda: discover.find(graph, city=label, limit=10), [])
    if isinstance(events, dict):
        events = events.get("items", [])
    feeds = safely(lambda: [f for f in ingest.feeds(graph)
                            if chat.slug(f.get("city", "") or "") == room], [])
    room_state = safely(lambda: chat.messages(graph, label, viewer_id=viewer_id, limit=5),
                        {"messages": []})
    people = safely(lambda: around(graph, label, viewer_id=viewer_id), [])

    empty = not (crew_list or events or feeds or room_state.get("messages") or people)
    return {
        "city": room,
        "label": label,
        "around": people,
        "you_are_here": bool(_my_presence(graph, label, viewer_id)) if viewer_id else False,
        "crews": crew_list,
        "events": events,
        "venue_feeds": len(feeds),
        "recent_chat": room_state.get("messages", []),
        "empty": empty,
        # What to *do* when there is nothing yet. An empty screen with no next step is how a
        # young instance loses the person who could have started its first crew.
        "suggestion": (
            f"Nothing in {label} yet — you are the first. Say hello in the room, or start a "
            f"crew and it will show up here for whoever lands next."
            if empty else ""),
    }
