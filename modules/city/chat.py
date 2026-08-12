"""City chat — one room per city, for travellers who do not know anyone yet.

Every social feature so far starts from a connection you already have: a crew you joined, an
event you were invited to, a person in your graph. This is the one that starts from nothing.
You land somewhere at 6pm knowing nobody, and there is a room with people in it.

**This is the first genuinely public space in LifeOS, and that changes the risk.** A crew has
an admission policy and an admin; a city room has neither — anyone signed in can read and
post. So the design is shaped around what goes wrong in public rooms rather than around the
happy path:

- **Messages are system-owned**, like venue listings. One city's conversation exists once,
  not once per account. Owner-scoped rows would mean everybody talking to themselves — the
  bug that made dating matches always return `is_mutual: False`.
- **Messages expire** (`RETENTION_DAYS`). Travellers are transient and so is the reason to
  keep what they said; a room that remembers everything forever is a permanent record of
  where somebody was on a given night, which is not a thing this app should hold.
- **Muting is personal and one-sided.** Blocking in a crew is an admin action; here, muting
  is yours alone, lives in your own slice, and the other person is never told. Nobody needs
  permission to stop reading someone.
- **Reports go to the operator, never to the room.** Same queue and same reasoning as
  `crews.report`: the person reported must not be able to read the report.
- **Posting reveals your city to strangers.** That is inherent — it is what the room is for —
  but it is worth saying plainly, because it is the one privacy trade a user is making here
  and they should make it knowingly. Only the handle is published, never the account's email
  or any identity linked to it.

What is deliberately *not* here: no direct messages (a stranger's inbox is a harassment
surface and `comms.chat` already exists for people you know), no editing (an edited message
above a reply rewrites someone else's context), and no per-room presence list, which is a
map of who is in a city tonight and is exactly the thing worth not building.
"""

import datetime
import re
import unicodedata

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "city.chat"
SCOPES = {"content:read", "content:write"}
RECORD = "city_message"
MUTE = "city_mute"
REPORT = "city_report"

MAX_TEXT = 1000
#: How long a message stays readable. A week is a traveller's window — long enough that a
#: room has a conversation in it, short enough that it is not a location history.
RETENTION_DAYS = 7
#: A flood guard independent of the gateway's per-IP limiter: that one stops a script,
#: this one stops one account filling a room from any number of addresses.
MAX_PER_WINDOW = 12
WINDOW_MINUTES = 5
DEFAULT_LIMIT = 100
MAX_LIMIT = 200


class ChatError(ValueError):
    """A message that cannot be posted, or a room that cannot be read."""


def _sys(graph: Graph):
    """The shared slice. A city room belongs to the instance, not to whoever spoke last."""
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def slug(city: str) -> str:
    """`Lisbon`, `lisbon`, ` LISBON `, `São Paulo` and `Sao Paulo` all have to reach one
    room, or the feature quietly splits into empty rooms nobody is in.

    Accents are folded rather than replaced: stripping non-ASCII directly turns `São Paulo`
    into `s-o-paulo`, so the people who type the name correctly end up in a different room
    from the people who do not — which is most of the world's cities and precisely the
    users this feature is for.
    """
    text = unicodedata.normalize("NFKD", str(city or "").strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        raise ChatError("which city?")
    return text[:60]


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _live(row: dict, now) -> bool:
    expires = _parse(row["attrs"].get("expires_at"))
    return expires is not None and expires > now and not row["attrs"].get("removed")


def muted_by(graph: Graph, viewer_id: str) -> set[str]:
    """Who this person has chosen not to hear. Kept in **their own** slice: a mute list is a
    statement about you, not about the person muted, and nobody else — including the muted
    person — has any business reading it."""
    if not viewer_id:
        return set()
    rows = graph.session(MODULE, SCOPES).find_entities(
        "content", {"type": MUTE, "owner_account": viewer_id}, limit=500)
    return {row["attrs"].get("target_id", "") for row in rows}


def mute(graph: Graph, viewer_id: str, target_id: str, source: str = MODULE) -> dict:
    """Stop seeing someone, immediately and silently. One-sided by design."""
    target_id = str(target_id or "").strip()
    if not target_id:
        raise ChatError("who do you want to mute?")
    if target_id == viewer_id:
        raise ChatError("you cannot mute yourself")
    session = graph.session(MODULE, SCOPES)
    for row in session.find_entities(
            "content", {"type": MUTE, "owner_account": viewer_id, "target_id": target_id},
            limit=1):
        return {"muted": True, "target_id": target_id, "already": True}
    session.create_entity("content", {
        "type": MUTE, "owner_account": viewer_id, "target_id": target_id,
        "created_at": now_iso()}, source=source)
    return {"muted": True, "target_id": target_id, "already": False}


def unmute(graph: Graph, viewer_id: str, target_id: str, source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    for row in session.find_entities(
            "content", {"type": MUTE, "owner_account": viewer_id,
                        "target_id": str(target_id or "").strip()}, limit=1):
        session.delete_entity(row["id"], source=source)
        return {"unmuted": True, "target_id": target_id}
    raise ChatError("you have not muted that person")


def post(graph: Graph, city: str, text: str, *, author_id: str, author_handle: str = "",
         source: str = MODULE) -> dict:
    """Say something in a city's room.

    `author_id` is the caller's account as established by the session — never a value off
    the request body. Letting a client name its own author is how one person posts as
    another, and this room is exactly where that would be used.
    """
    room = slug(city)
    body = str(text or "").strip()
    if not body:
        raise ChatError("an empty message says nothing")
    if len(body) > MAX_TEXT:
        raise ChatError(f"messages are capped at {MAX_TEXT} characters")
    if not author_id:
        raise ChatError("sign in to post")

    session = _sys(graph)
    now = _now()

    recent = [row for row in session.find_entities(
        "content", {"type": RECORD, "city": room, "author_id": author_id}, limit=200)
        if (made := _parse(row["attrs"].get("created_at"))) is not None
        and made > now - datetime.timedelta(minutes=WINDOW_MINUTES)]
    if len(recent) >= MAX_PER_WINDOW:
        raise ChatError(
            f"that is a lot of messages at once — wait a few minutes before posting again")

    message_id = session.create_entity("content", {
        "type": RECORD, "city": room, "city_label": str(city or "").strip()[:80],
        "author_id": author_id, "author_handle": str(author_handle or "")[:80],
        "text": body, "created_at": now_iso(),
        "expires_at": (now + datetime.timedelta(days=RETENTION_DAYS)).isoformat(),
    }, source=source, owner_id=SYSTEM_OWNER)

    return {"message_id": message_id, "city": room, "text": body,
            "expires_in_days": RETENTION_DAYS}


def _render(row: dict, viewer_id: str) -> dict:
    attrs = row["attrs"]
    return {
        "message_id": row["id"],
        "city": attrs.get("city", ""),
        "author_id": attrs.get("author_id", ""),
        "author_handle": attrs.get("author_handle") or "someone",
        "text": attrs.get("text", ""),
        "created_at": attrs.get("created_at", ""),
        "mine": attrs.get("author_id") == viewer_id,
    }


def messages(graph: Graph, city: str, *, viewer_id: str = "",
             limit: int = DEFAULT_LIMIT) -> dict:
    """The room, oldest first, with anyone the viewer has muted left out."""
    room = slug(city)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    now = _now()
    hidden = muted_by(graph, viewer_id)

    rows = [row for row in _sys(graph).find_entities(
        "content", {"type": RECORD, "city": room}, limit=MAX_LIMIT * 4) if _live(row, now)]
    rows.sort(key=lambda r: str(r["attrs"].get("created_at", "")))
    visible = [_render(row, viewer_id) for row in rows
               if row["attrs"].get("author_id") not in hidden]

    return {"city": room, "messages": visible[-limit:],
            "muted": len(rows) - len(visible),
            "retention_days": RETENTION_DAYS}


def remove_own(graph: Graph, message_id: str, *, author_id: str,
               source: str = MODULE) -> dict:
    """Take back something you said. Yours only — `delete_entity` cannot be used here
    because the row is system-owned, so authorship is checked explicitly."""
    session = _sys(graph)
    row = session.get_entity(message_id)
    if row is None or row["attrs"].get("type") != RECORD:
        raise ChatError("unknown message")
    if row["attrs"].get("author_id") != author_id:
        raise ChatError("that is not your message")
    session.update_entity(message_id, {"removed": True, "text": ""}, source=source)
    return {"removed": True, "message_id": message_id}


def report(graph: Graph, message_id: str, *, reporter_id: str, reason: str,
           source: str = MODULE) -> dict:
    """Flag a message for the operator. Never visible in the room, and never to its author —
    see the reasoning on `_operator` in the gateway."""
    reason = str(reason or "").strip()[:500]
    if not reason:
        raise ChatError("a report needs a reason")
    session = _sys(graph)
    row = session.get_entity(message_id)
    if row is None or row["attrs"].get("type") != RECORD:
        raise ChatError("unknown message")

    report_id = session.create_entity("content", {
        "type": REPORT, "message_id": message_id,
        "city": row["attrs"].get("city", ""),
        "subject_id": row["attrs"].get("author_id", ""),
        "reporter_id": reporter_id,
        # The text is copied because the message expires in a week and a report that has
        # lost its evidence cannot be acted on.
        "quoted_text": row["attrs"].get("text", "")[:MAX_TEXT],
        "reason": reason, "status": "open", "created_at": now_iso(),
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"report_id": report_id, "status": "open"}


def open_reports(graph: Graph, limit: int = 100) -> list[dict]:
    """Operator-only; the gateway enforces that."""
    out = []
    for row in _sys(graph).find_entities("content", {"type": REPORT}, limit=limit):
        attrs = row["attrs"]
        if attrs.get("status") != "open":
            continue
        out.append({"report_id": row["id"], "city": attrs.get("city"),
                    "message_id": attrs.get("message_id"),
                    "subject_id": attrs.get("subject_id"),
                    "reporter_id": attrs.get("reporter_id"),
                    "quoted_text": attrs.get("quoted_text"),
                    "reason": attrs.get("reason"),
                    "created_at": attrs.get("created_at")})
    return out


def resolve_report(graph: Graph, report_id: str, action: str = "actioned",
                   *, remove_message: bool = False, source: str = MODULE) -> dict:
    if action not in ("actioned", "dismissed"):
        raise ChatError("action must be 'actioned' or 'dismissed'")
    session = _sys(graph)
    row = session.get_entity(report_id)
    if row is None or row["attrs"].get("type") != REPORT:
        raise ChatError("unknown report")
    session.update_entity(report_id, {"status": action, "resolved_at": now_iso()},
                          source=source)
    if remove_message and row["attrs"].get("message_id"):
        target = session.get_entity(row["attrs"]["message_id"])
        if target is not None:
            session.update_entity(target["id"], {"removed": True, "text": ""}, source=source)
    return {"report_id": report_id, "status": action,
            "message_removed": bool(remove_message)}


def active_cities(graph: Graph, limit: int = 30) -> list[dict]:
    """Where the conversations are. This is what makes the feature discoverable — a room you
    have to guess the name of is a room nobody enters. Counts only, never who is in them."""
    now = _now()
    tally: dict[str, dict] = {}
    for row in _sys(graph).find_entities("content", {"type": RECORD}, limit=2000):
        if not _live(row, now):
            continue
        attrs = row["attrs"]
        room = attrs.get("city", "")
        entry = tally.setdefault(room, {"city": room,
                                        "label": attrs.get("city_label") or room,
                                        "messages": 0, "voices": set(),
                                        "last_at": ""})
        entry["messages"] += 1
        entry["voices"].add(attrs.get("author_id", ""))
        stamp = str(attrs.get("created_at", ""))
        if stamp > entry["last_at"]:
            entry["last_at"] = stamp

    rooms = [{"city": e["city"], "label": e["label"], "messages": e["messages"],
              "voices": len(e["voices"]), "last_at": e["last_at"]}
             for e in tally.values()]
    rooms.sort(key=lambda r: r["last_at"], reverse=True)
    return rooms[:limit]
