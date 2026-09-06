"""The list of people an organiser is expecting at their own meetup.

`POST /events/vip-guestlist` answered `granted: True` to anybody who asked, for a venue that
defaulted to "Miradouro Rooftop Bar", with `access_tier: "VIP_FAST_TRACK"` and
`pass_code: "VIP-KARMA-98"` — the same code for every caller on every deployment, honoured
by nobody, next to a karma score of 98 that this app has never computed for anyone. Somebody
could have shown that code on a door.

Underneath it there is a real thing an organiser wants: *these are the people I am
expecting*. So:

- **Only the organiser writes it**, on a meetup that exists. It is their door.
- **Guests are accounts**, resolved from handles by the caller before they reach here. A
  guest list of typed strings is a list nobody can be told they are on — the same reason the
  shared tab refuses a name that resolves to nobody.
- **The people it concerns can read it**: the organiser, anybody on the list, and anybody
  who has said they are going. Not the whole city — who is expected at a private gathering
  is not public information.
- **There is no tier, no fast track and no code.** This app cannot grant entry to anywhere,
  and minting a code that a venue has never seen is worse than useless: it is something
  somebody relies on at a door.
"""

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import meetups

MODULE = "city.guestlist"
SCOPES = {"content:read", "content:write"}
RECORD = "meetup_guestlist"

MAX_GUESTS = 100
MAX_NOTE = 200

NO_ENTRY = ("This is the organiser's own list of who they are expecting. It grants nothing "
            "and no venue has seen it — there is no pass and no code.")


class GuestlistError(ValueError):
    """A guest list that cannot be written or read."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _meetup(session, meetup_id: str) -> dict:
    """The meetup this list belongs to, or a refusal.

    Read through the same system session the meetups module writes with, and checked by
    `attrs["type"]`: an id that points at some other row must not become an empty guest list
    for a gathering that does not exist.
    """
    meetup_id = str(meetup_id or "").strip()
    if not meetup_id:
        raise GuestlistError("which meetup? pass `meetup_id`")
    row = session.get_entity(meetup_id)
    if row is None or row["attrs"].get("type") != meetups.RECORD:
        raise GuestlistError("unknown meetup")
    return row


def _list_row(session, meetup_id: str):
    rows = session.find_entities("content", {"type": RECORD, "meetup_id": meetup_id},
                                 limit=5)
    return rows[0] if rows else None


def add(graph: Graph, meetup_id: str, *, guests: list, account_id: str,
        handles: dict | None = None, note: str = "", source: str = MODULE) -> dict:
    """Put people on the list. Adding is idempotent: the same person twice is one guest."""
    if not account_id:
        raise GuestlistError("sign in first")
    session = _sys(graph)
    meetup = _meetup(session, meetup_id)
    if meetup["attrs"].get("organiser_id") != account_id:
        raise GuestlistError("only the organiser keeps the list for their own meetup")

    wanted = [str(guest or "").strip() for guest in (guests or []) if str(guest or "").strip()]
    if not wanted:
        raise GuestlistError("who is on the list?")

    row = _list_row(session, meetup["id"])
    listed = list(row["attrs"].get("guests") or []) if row else []
    known = dict(row["attrs"].get("handles") or {}) if row else {}
    for guest in wanted:
        if guest not in listed:
            listed.append(guest)
    known.update({k: str(v or "")[:80] for k, v in (handles or {}).items()})
    if len(listed) > MAX_GUESTS:
        raise GuestlistError(f"that is more than {MAX_GUESTS} people")

    attrs = {"guests": listed, "handles": known,
             "note": str(note or "").strip()[:MAX_NOTE]}
    if row is None:
        row_id = session.create_entity("content", {
            "type": RECORD, "meetup_id": meetup["id"],
            "organiser_id": account_id,
            "city": meetup["attrs"].get("city", ""),
            "created_at": now_iso(), **attrs,
        }, source=source, owner_id=SYSTEM_OWNER)
    else:
        row_id = row["id"]
        session.update_entity(row_id, attrs, source=source)

    return {"added": len(wanted), "guestlist_id": row_id, "meetup_id": meetup["id"],
            "title": meetup["attrs"].get("title", ""),
            "place": meetup["attrs"].get("place", ""),
            "guest_count": len(listed), "granted": False, "no_entry": NO_ENTRY,
            "safety_note": meetups.SAFETY_NOTE}


def remove(graph: Graph, meetup_id: str, *, guest: str, account_id: str,
           source: str = MODULE) -> dict:
    """Take somebody off. The organiser's list, so the organiser's call."""
    session = _sys(graph)
    meetup = _meetup(session, meetup_id)
    if meetup["attrs"].get("organiser_id") != account_id:
        raise GuestlistError("only the organiser keeps the list for their own meetup")
    row = _list_row(session, meetup["id"])
    if row is None:
        return {"removed": False, "meetup_id": meetup["id"], "guest_count": 0}
    listed = [person for person in (row["attrs"].get("guests") or [])
              if person != str(guest or "").strip()]
    session.update_entity(row["id"], {"guests": listed}, source=source)
    return {"removed": True, "meetup_id": meetup["id"], "guest_count": len(listed)}


def listing(graph: Graph, meetup_id: str, *, viewer_id: str = "") -> dict:
    """Read the list, if it is yours to read.

    "Yours" is: you organised it, you are on it, or you have said you are going. A guest
    list is a small piece of somebody's social life and the city does not need it.
    """
    session = _sys(graph)
    meetup = _meetup(session, meetup_id)
    attrs = meetup["attrs"]
    row = _list_row(session, meetup["id"])
    listed = list(row["attrs"].get("guests") or []) if row else []
    known = dict(row["attrs"].get("handles") or {}) if row else {}

    organiser = attrs.get("organiser_id", "")
    going = list(attrs.get("going") or [])
    if viewer_id not in ([organiser] + listed + going):
        raise GuestlistError("that list is not yours to read")

    meetup_handles = dict(attrs.get("handles") or {})
    guests = [{"account_id": guest,
               "handle": known.get(guest) or meetup_handles.get(guest) or "someone",
               "going": guest in going,
               "you": guest == viewer_id}
              for guest in listed]

    return {"meetup_id": meetup["id"], "title": attrs.get("title", ""),
            "place": attrs.get("place", ""), "starts_at": attrs.get("starts_at", ""),
            "organiser_id": organiser,
            "organiser_handle": attrs.get("organiser_handle") or "someone",
            "yours": viewer_id == organiser,
            "guests": guests, "count": len(guests), "empty": not guests,
            "you_are_on_it": viewer_id in listed,
            "note": row["attrs"].get("note", "") if row else "",
            "granted": False, "no_entry": NO_ENTRY,
            "safety_note": meetups.SAFETY_NOTE,
            "suggestion": "" if guests else (
                "Nobody is on this list yet. The organiser adds people by handle.")}
