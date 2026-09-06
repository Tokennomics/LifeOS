"""The small things people send each other — kudos, reviews, moments, check-ins.

Four endpoints claimed to do this and none of them stored anything. `/kudos/send` returned a
"kudos karma" total that was a constant. `/social/kindness` reported a kindness streak.
`/feed/reviews` returned three reviews of Lisbon venues signed by people who do not exist.
`/moments/flash` created an ephemeral photo moment with a view count.

They are one kind of object with four faces: a short, attributable note from one real account
about a person, a place or a night. So there is one record and one set of rules.

**Who can read what is the whole design.** These are the first things in the app that one
person writes *about another*, and the failure mode is not an invented number this time — it
is somebody being talked about where they cannot see it.

- **Kudos are addressed.** The recipient can always read a kudos about them. That is the
  point of sending one, and it also means nobody can build a private file on somebody.
- **Reviews are about places, never people.** A review of a person is a rating system, and
  this app deliberately has none — the karma score was removed for exactly that reason.
- **Moments are public in a city and expire**, like the room they sit next to.
- **Check-ins are yours.** A check-in says you were somewhere; it is owner-scoped, and it is
  what makes "I was there" true rather than minted.

Nothing here has a score, a streak or a leaderboard. Every count is a count of rows.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat

MODULE = "social.signals"
SCOPES = {"content:read", "content:write"}

KUDOS = "kudos"
REVIEW = "place_review"
MOMENT = "city_moment"
CHECKIN = "checkin"

MAX_TEXT = 500
MAX_LISTED = 50
MOMENT_HOURS = 24


class SignalError(ValueError):
    """Something that cannot be sent, written or checked into."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _own(graph: Graph):
    return graph.session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _text(value, cap: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:cap]


# ---- kudos -------------------------------------------------------------------

def send_kudos(graph: Graph, to_account: str, note: str, *, account_id: str,
               handle: str = "", kind: str = "kudos", source: str = MODULE) -> dict:
    """Say thank you to somebody, where they can read it.

    System-owned rather than owner-scoped, because a note the recipient cannot see is not a
    kudos — it is a private record about a person, which is a different and much worse
    object. The trade is deliberate: everything written here is readable by its subject.
    """
    to_account = str(to_account or "").strip()
    note = _text(note)
    if not account_id:
        raise SignalError("sign in first")
    if not to_account:
        raise SignalError("who is it for?")
    if to_account == account_id:
        raise SignalError("kudos are for other people")
    if not note:
        raise SignalError("what are you thanking them for?")

    kudos_id = _sys(graph).create_entity("content", {
        "type": KUDOS, "kind": _text(kind, 40) or "kudos",
        "from_account": account_id, "from_handle": _text(handle, 80),
        "to_account": to_account, "note": note, "created_at": now_iso(),
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"sent": True, "kudos_id": kudos_id, "to_account": to_account,
            "visible_to_them": True,
            "no_score": "No karma, no streak — this is a note, not a currency."}


def _render_kudos(row: dict) -> dict:
    attrs = row["attrs"]
    return {"kudos_id": row["id"], "kind": attrs.get("kind", ""),
            "note": attrs.get("note", ""),
            "from_handle": attrs.get("from_handle") or "someone",
            "from_account": attrs.get("from_account", ""),
            "to_account": attrs.get("to_account", ""),
            "created_at": attrs.get("created_at", "")}


def kudos_for(graph: Graph, account_id: str, *, direction: str = "received",
              limit: int = MAX_LISTED) -> dict:
    """What was said to you, or what you said. Never a third party's."""
    if not account_id:
        raise SignalError("sign in first")
    field = "to_account" if direction == "received" else "from_account"
    rows = _sys(graph).find_entities("content", {"type": KUDOS, field: account_id},
                                     limit=MAX_LISTED * 2)
    items = [_render_kudos(r) for r in rows]
    items.sort(key=lambda k: k["created_at"], reverse=True)
    return {"direction": direction, "kudos": items[:limit], "total": len(items),
            "empty": not items}


# ---- reviews of places -------------------------------------------------------

def write_review(graph: Graph, city: str, place: str, text: str, *, account_id: str,
                 handle: str = "", rating: int | None = None,
                 place_id: str = "", source: str = MODULE) -> dict:
    """A review of a place. Never of a person.

    Rating is optional and bounded, and it is attached to a venue — a rating attached to a
    human being is the karma score under another name, and that was removed on its merits.
    """
    if not account_id:
        raise SignalError("sign in first")
    place = _text(place, 120)
    text = _text(text)
    if not place:
        raise SignalError("which place?")
    if not text:
        raise SignalError("say something about it")
    if rating is not None:
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            raise SignalError("rating must be a number")
        if not 1 <= rating <= 5:
            raise SignalError("rating is 1 to 5")

    room = chat.slug(city) if str(city or "").strip() else ""
    review_id = _sys(graph).create_entity("content", {
        "type": REVIEW, "city": room, "city_label": _text(city, 80),
        "place": place, "place_id": _text(place_id, 60),
        "text": text, "rating": rating,
        "author_account": account_id, "author_handle": _text(handle, 80),
        "created_at": now_iso(),
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"written": True, "review_id": review_id, "place": place, "city": room,
            "about": "a place — this app does not rate people"}


def reviews(graph: Graph, *, city: str = "", place_id: str = "",
            limit: int = MAX_LISTED) -> dict:
    query = {"type": REVIEW}
    if city:
        query["city"] = chat.slug(city)
    if place_id:
        query["place_id"] = place_id
    rows = _sys(graph).find_entities("content", query, limit=MAX_LISTED * 2)
    items = [{"review_id": r["id"], "place": r["attrs"].get("place", ""),
              "text": r["attrs"].get("text", ""), "rating": r["attrs"].get("rating"),
              "author_handle": r["attrs"].get("author_handle") or "someone",
              "created_at": r["attrs"].get("created_at", "")} for r in rows]
    items.sort(key=lambda r: r["created_at"], reverse=True)
    return {"reviews": items[:limit], "total": len(items), "empty": not items,
            "suggestion": "" if items else (
                "No reviews here yet. Yours would be the first, which is worth more than "
                "the hundredth.")}


# ---- moments -----------------------------------------------------------------

def post_moment(graph: Graph, city: str, caption: str, *, account_id: str,
                handle: str = "", source: str = MODULE) -> dict:
    """A short public note about tonight, in a city, that expires.

    No photo. The old endpoint reported an ephemeral *photo* moment with a view count; there
    is no image pipeline in this app, and a caption is the honest subset of the idea.
    """
    if not account_id:
        raise SignalError("sign in first")
    if not str(city or "").strip():
        raise SignalError("which city?")
    caption = _text(caption, 200)
    if not caption:
        raise SignalError("say something")

    moment_id = _sys(graph).create_entity("content", {
        "type": MOMENT, "city": chat.slug(city), "city_label": _text(city, 80),
        "caption": caption, "account_id": account_id, "handle": _text(handle, 80),
        "created_at": now_iso(),
        "expires_at": (_now() + datetime.timedelta(hours=MOMENT_HOURS)).isoformat(),
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"posted": True, "moment_id": moment_id, "expires_in_hours": MOMENT_HOURS,
            "no_views": "Nothing counts views here."}


def moments(graph: Graph, city: str, *, viewer_id: str = "",
            limit: int = MAX_LISTED) -> dict:
    room = chat.slug(city) if str(city or "").strip() else ""
    if not room:
        raise SignalError("which city?")
    now = _now()
    hidden = chat.muted_by(graph, viewer_id)
    items = []
    for row in _sys(graph).find_entities("content", {"type": MOMENT, "city": room},
                                         limit=MAX_LISTED * 4):
        attrs = row["attrs"]
        expires = _parse(attrs.get("expires_at", ""))
        if expires is None or expires <= now or attrs.get("account_id") in hidden:
            continue
        items.append({"moment_id": row["id"], "caption": attrs.get("caption", ""),
                      "handle": attrs.get("handle") or "someone",
                      "created_at": attrs.get("created_at", ""),
                      "mine": attrs.get("account_id") == viewer_id})
    items.sort(key=lambda m: m["created_at"], reverse=True)
    return {"city": room, "moments": items[:limit], "empty": not items}


# ---- check-ins ---------------------------------------------------------------

def check_in(graph: Graph, *, account_id: str, place: str = "", place_id: str = "",
             meetup_id: str = "", city: str = "", source: str = MODULE) -> dict:
    """Record that you were somewhere.

    `/events/qr-checkin` scanned a code and returned `checked_in: True` with a bonus karma
    award, for any string. `/gamification/mint-presence` minted a "POP-" token as proof of
    presence — a token nobody issued, on no chain, verifying nothing.

    A check-in is owner-scoped: it is your record of your evening. It is also what
    `personal.recap` counts, so the number of outings you have been to becomes true rather
    than asserted.
    """
    if not account_id:
        raise SignalError("sign in first")
    place = _text(place, 120)
    if not (place or place_id or meetup_id):
        raise SignalError("where?")

    checkin_id = _own(graph).create_entity("content", {
        "type": CHECKIN, "place": place, "place_id": _text(place_id, 60),
        "meetup_id": _text(meetup_id, 60),
        "city": chat.slug(city) if str(city or "").strip() else "",
        "created_at": now_iso(),
    }, source=source)
    return {"checked_in": True, "checkin_id": checkin_id, "place": place,
            "minted": False,
            "note": ("This is your own record that you were there. Nothing is minted and "
                     "nobody is awarded anything.")}


def check_ins(graph: Graph, *, limit: int = MAX_LISTED) -> dict:
    rows = _own(graph).find_entities("content", {"type": CHECKIN}, limit=MAX_LISTED * 2)
    items = [{"checkin_id": r["id"], "place": r["attrs"].get("place", ""),
              "city": r["attrs"].get("city", ""),
              "created_at": r["attrs"].get("created_at", "")} for r in rows]
    items.sort(key=lambda c: c["created_at"], reverse=True)
    return {"check_ins": items[:limit], "total": len(items), "empty": not items}
