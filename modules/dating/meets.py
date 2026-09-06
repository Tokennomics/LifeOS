"""Who is open to meeting someone here — the discovery half of dating.

`mutual_match` already does the hard part correctly: interest in a *named* person is
declared as a blinded digest, and neither side learns anything until both have declared.
What it cannot do is tell you who to name. Without that, dating worked only between people
who already knew each other's account ids, which is not dating.

`/dating/instant-meet` filled that gap with Elena R., 1.2 km away, at a 96% "7-factor"
score computed from seven constants. This is the real version, and the thing it must not
become is a browsable list of who is single in a city.

Four rules do that work:

- **Reciprocal visibility.** You cannot see who is open unless you are open yourself. This
  is the rule that matters most: it makes lurking impossible, so the list is only ever
  visible to people who accepted being on it. Reading is not enough to publish you either —
  publishing is its own call.
- **Gated exactly as the rest of the surface.** `gate.require_surface()` and
  `require_adult()` run before anything is written *or* read, so an instance with dating off,
  or a caller who has not declared an adult date of birth, sees nothing rather than a
  degraded version.
- **Blocks and mutes cut both ways.** Someone you blocked never appears, and — the half
  that is easy to forget — you never appear to them either. A one-directional filter shows
  the blocked party a person who cannot see them, which is worse than showing nothing.
- **City granularity, expiring.** No coordinates, no venue, no "online now". A marker lasts
  `DEFAULT_HOURS` and dies on its own.

What comes back is a handle, a vibe and an `account_id` — the id being the point, because it
is the argument to `express_interest`. From there the existing consent handshake takes over
and this module is finished.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat
from modules.dating import gate, safety

MODULE = "dating.meets"
SCOPES = {"content:read", "content:write"}
RECORD = "dating_open"

DEFAULT_HOURS = 6
MAX_HOURS = 48
MAX_VIBE = 100
MAX_RESULTS = 50

SAFETY_NOTE = ("Meet somewhere public the first time, tell someone where you are going, "
               "and arrange your own way home.")


class MeetError(ValueError):
    """A marker that cannot be published, or a list that cannot be read."""


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


def _gated(graph: Graph, account_id: str) -> str:
    """Every entry point in this module starts here. The surface check comes before the
    adult check so an instance with dating switched off never reads anybody's date of
    birth to answer a question it was not going to answer."""
    gate.require_surface()
    who = str(account_id or "").strip()
    if not who:
        raise MeetError("sign in first")
    gate.require_adult(graph, who)
    return who


def open_to_meeting(graph: Graph, city: str, *, account_id: str, handle: str = "",
                    vibe: str = "", hours: int = DEFAULT_HOURS,
                    source: str = MODULE) -> dict:
    """Say you are open to meeting someone in this city, until it expires.

    Re-opening the same city replaces the previous marker rather than stacking.
    """
    me = _gated(graph, account_id)
    if not str(city or "").strip():
        raise MeetError("which city?")
    room = chat.slug(city)

    if hours is None:
        hours = DEFAULT_HOURS
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        raise MeetError("hours must be a number")
    if hours < 1 or hours > MAX_HOURS:
        raise MeetError(f"pick between 1 and {MAX_HOURS} hours")

    session = _sys(graph)
    for row in session.find_entities(
            "content", {"type": RECORD, "city": room, "account_id": me}, limit=20):
        session.update_entity(row["id"], {"withdrawn": True}, source=source)

    marker_id = session.create_entity("content", {
        "type": RECORD, "city": room, "city_label": str(city or "").strip()[:80],
        "account_id": me, "handle": str(handle or "")[:80],
        "vibe": str(vibe or "").strip()[:MAX_VIBE],
        "created_at": now_iso(),
        "expires_at": (_now() + datetime.timedelta(hours=hours)).isoformat(),
        "withdrawn": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"open": True, "marker_id": marker_id, "city": room, "hours": hours,
            "safety_note": SAFETY_NOTE}


def close(graph: Graph, city: str = "", *, account_id: str, source: str = MODULE) -> dict:
    """Take it down. No city given takes down every marker, everywhere — the thing you want
    when you have stopped wanting this at all, and it should not require remembering which
    cities you left one in."""
    me = _gated(graph, account_id)
    room = chat.slug(city) if str(city or "").strip() else ""
    session = _sys(graph)
    closed = 0
    for row in session.find_entities("content", {"type": RECORD, "account_id": me},
                                     limit=200):
        if row["attrs"].get("withdrawn"):
            continue
        if room and row["attrs"].get("city") != room:
            continue
        session.update_entity(row["id"], {"withdrawn": True}, source=source)
        closed += 1
    return {"closed": closed, "city": room}


def _my_marker(graph: Graph, room: str, me: str):
    now = _now()
    for row in _sys(graph).find_entities(
            "content", {"type": RECORD, "city": room, "account_id": me}, limit=20):
        if _live(row, now):
            return row
    return None


def nearby(graph: Graph, city: str, *, account_id: str,
           limit: int = MAX_RESULTS) -> dict:
    """Who else is open here.

    Returns `you_are_open: False` and an empty list rather than raising when the caller has
    not published: "you have to be on the list to read the list" is a rule to explain, not
    an error to throw at somebody who just tapped a button.
    """
    me = _gated(graph, account_id)
    if not str(city or "").strip():
        raise MeetError("which city?")
    room = chat.slug(city)
    label = str(city or "").strip()

    if _my_marker(graph, room, me) is None:
        return {
            "city": room, "city_label": label, "you_are_open": False,
            "people": [], "people_count": 0,
            "suggestion": ("You can see who is open here once you are open yourself. "
                           "Nobody browses this list from the outside."),
            "safety_note": SAFETY_NOTE,
        }

    now = _now()
    hidden = chat.muted_by(graph, me)
    people = []
    for row in _sys(graph).find_entities("content", {"type": RECORD, "city": room},
                                         limit=MAX_RESULTS * 4):
        if not _live(row, now):
            continue
        attrs = row["attrs"]
        them = attrs.get("account_id", "")
        if not them or them == me or them in hidden:
            continue
        # Both directions. A one-way check leaves the blocked party looking at somebody who
        # cannot see them, which is the interaction a block exists to prevent.
        if safety.is_blocked(graph, me, them) or safety.is_blocked(graph, them, me):
            continue
        people.append({
            "account_id": them,
            "handle": attrs.get("handle") or "someone",
            "vibe": attrs.get("vibe", ""),
            "open_until": attrs.get("expires_at", ""),
        })

    people.sort(key=lambda p: p["open_until"])
    people = people[:limit]
    return {
        "city": room, "city_label": label, "you_are_open": True,
        "people": people, "people_count": len(people),
        # The next step is a named, private declaration — not a message and not a reveal.
        "next_step": ("Interest is private: express it in someone and nothing is shown to "
                      "them unless they express it in you too."),
        "suggestion": "" if people else (
            f"Nobody else is open in {label} right now. Your marker is up, so the next "
            f"person to look will see you."),
        "safety_note": SAFETY_NOTE,
    }


def mine(graph: Graph, *, account_id: str) -> list[dict]:
    """Every marker you have up, in any city."""
    me = _gated(graph, account_id)
    now = _now()
    out = []
    for row in _sys(graph).find_entities("content", {"type": RECORD, "account_id": me},
                                         limit=200):
        if not _live(row, now):
            continue
        attrs = row["attrs"]
        out.append({"marker_id": row["id"], "city": attrs.get("city", ""),
                    "city_label": attrs.get("city_label", ""),
                    "vibe": attrs.get("vibe", ""),
                    "expires_at": attrs.get("expires_at", "")})
    out.sort(key=lambda m: m["expires_at"])
    return out


def meeting_code(a: str, b: str, activity: str) -> str:
    """A short code both sides of a match see, and nobody else can guess.

    Replaces `"pin_code": "4892"`, which was the same four digits for every pair in the
    world and therefore verified nothing. Derived from the signing key over the *unordered*
    pair, so Ana and Bruno independently compute the same code while a different pair gets
    a different one. Six digits: it is a "is this the person I am meeting" check made out
    loud, not a credential — it authorises nothing and unlocks nothing.
    """
    from modules.security import crypto_tokens

    low, high = sorted([str(a), str(b)])
    digest = crypto_tokens.sign_payload({
        "ns": "dating/meeting-code/v1",
        "pair": [low, high], "activity": str(activity),
    })
    return f"{int(digest[:8], 16) % 1000000:06d}"


def agree(graph: Graph, target_account_id: str, activity_id: str, *,
          account_id: str, source: str = MODULE) -> dict:
    """Say yes to meeting one specific person, and find out whether they said it too.

    This is `express_interest` with the meeting attached, so a caller cannot end up
    "agreed" with somebody who never agreed. The old endpoint returned `agreed: True` and a
    map pin for any name in the body, including a name typed by hand — it confirmed a
    meeting with a person who had not been asked.
    """
    from modules.dating import mutual_match

    me = _gated(graph, account_id)
    target_account_id = str(target_account_id or "").strip()
    activity_id = str(activity_id or "").strip() or "meet"
    if not target_account_id:
        raise MeetError("who?")

    outcome = mutual_match.express_interest(graph, target_account_id, activity_id,
                                            account_id=me, source=source)
    both = bool(outcome.get("is_mutual"))
    return {
        # `agreed` now means both sides did, which is the only thing the word can mean.
        "agreed": both,
        "target_account_id": target_account_id,
        "activity_id": activity_id,
        "outcome": outcome.get("outcome"),
        # Only ever shown once it is actually mutual — before that there is no meeting.
        "meeting_code": meeting_code(me, target_account_id, activity_id) if both else "",
        "message": ("You are both in. Agree a public place and a time in chat."
                    if both else
                    "Noted privately. They will not be told unless they say the same."),
        "safety_note": SAFETY_NOTE,
    }
