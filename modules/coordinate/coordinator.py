"""Coordinate — the graph-backed 1:1 reconnect flow.

Steps (single round, human-ratified):
  1. propose(person, slots, places, owner_weights)  -> a coordination record + a shareable ask
  2. respond(id, peer_weights)                      -> ranks the overlap into candidates
  3. approve(id, side, choice)                      -> each side approves one candidate
  4. (on matching approval) confirm                 -> writes the meet event `with` the person

The coordination lives as a `content` entity (attrs.type = "coordination"); the confirmed
meet is an `event` (busy block) linked to the person. Every write carries provenance
(module = coordinate). Peer weights are sanitized to the proposed slots/places before use —
untrusted input never widens the key space or carries free text.

**Group sessions span accounts.** A crew's members may live in other accounts entirely, and
the owner scope that keeps everything else private would stop them answering a session the
organiser opened. The ACL settles it: opening a group session grants every current crew
member `coord:participant` on the coordination, and that grant — nothing else — is what lets
them read it, add their own availability, and approve. It confers no access to anything else
the organiser owns, and it is withdrawn the moment they leave (or are blocked from) the crew.
"""

import datetime

from modules.coordinate import core
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "people:read", "events:read", "events:write"}
MODULE = "coordinate"
SIDES = ("owner", "peer")
PARTICIPANT = "coord:participant"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _clean_labels(items, cap: int = 20) -> list[str]:
    out = []
    for x in (items or []):
        s = str(x).strip()[:120]
        if s and s not in out:
            out.append(s)
        if len(out) >= cap:
            break
    return out


def _sanitize_weights(weights: dict, slots: list[str], places: list[str]) -> dict:
    """Keep only weights over the PROPOSED slots/places, coerced to sane numbers.

    This is the trust boundary for peer input: extra/injected keys are dropped, values
    are clamped to [0, 10], slots default to 0 (must opt in), places to 1 (opt out with 0).
    """
    weights = weights or {}
    sw_in = weights.get("slots", {}) or {}
    pw_in = weights.get("places", {}) or {}
    clamp = lambda v, d: max(0.0, min(10.0, core._num(v if v is not None else d)))
    slot_w = {s: clamp(sw_in.get(s), 0) for s in slots if clamp(sw_in.get(s), 0) > 0}
    place_w = {p: clamp(pw_in.get(p), 1) for p in places}
    return {"slots": slot_w, "places": place_w}


def _load(session, coord_id: str) -> dict:
    coord = session.get_entity(coord_id)
    if coord is None or coord["kind"] != "content" or coord["attrs"].get("type") != "coordination":
        raise ValueError("unknown coordination")
    return coord


def _view(coord: dict) -> dict:
    a = coord["attrs"]
    view = {"id": coord["id"], "mode": a.get("mode", "pair"), "person_id": a.get("person_id"),
            "person_name": a.get("person_name"), "status": a.get("status"),
            "slots": a.get("slots", []), "places": a.get("places", []),
            "candidates": a.get("candidates", []), "approvals": a.get("approvals", {}),
            "event_id": a.get("event_id")}
    if a.get("mode") == "group":
        view.update({"crew_id": a.get("crew_id"), "crew_name": a.get("crew_name"),
                     "quorum": a.get("quorum"), "responded": sorted(a.get("weights", {})),
                     "confirmed": a.get("confirmed")})
    return view


# ---- shared access: the organiser owns it, participants were granted it ------


def _load_shared(session, coord_id: str, subject: str | None) -> tuple[dict, bool]:
    """The session as its organiser owns it, or as a granted participant sees it.

    Returns (coordination, is_mine). Without ownership *and* without a participant grant
    the session reads as unknown — the same answer an id that doesn't exist gets.
    """
    coord = session.get_entity(coord_id)
    if coord is not None and coord["kind"] == "content" and coord["attrs"].get("type") == "coordination":
        return coord, True
    coord = session.get_if_granted(coord_id, subject, {PARTICIPANT}) if subject else None
    if coord is None or coord["kind"] != "content" or coord["attrs"].get("type") != "coordination":
        raise ValueError("unknown coordination")
    return coord, False


def _write(session, coord_id: str, patch: dict, subject: str | None, is_mine: bool,
           source: str) -> None:
    """Own it, or write through the participant grant. A participant only ever patches the
    shared planning state (their availability, their approval) — never anything else."""
    if is_mine:
        session.update_entity(coord_id, patch, source=source)
    else:
        session.update_if_granted(coord_id, patch, subject, {PARTICIPANT}, source=source)


def _sync_participants(session, coord: dict, members: set, source: str) -> list[str]:
    """Make the participant grants match the crew's CURRENT membership.

    Membership moves while a session is open: someone joins the crew on Tuesday and should
    be able to answer Friday's plan; someone who left — or was blocked — should lose it.
    The list is always derived from the crew, never from caller input.
    """
    current = {g["subject"] for g in session.grants_for(coord["id"]) if g["scope"] == PARTICIPANT}
    for sid in sorted(members - current):
        session.grant(sid, PARTICIPANT, coord["id"], source=source)
    for sid in sorted(current - members):
        session.revoke(sid, PARTICIPANT, coord["id"], source=source)
    return sorted(members)


def _authorise(graph: Graph, session, coord: dict, subject: str, is_mine: bool,
               source: str) -> set:
    """Who may act on this session: the crew's current members, and nobody else.

    Two separate things have to hold, and each does a job the other can't.

      - The participant GRANT is what lets a member in another account *reach* the
        coordination at all; without it the entity is out of their owner scope and reads
        as missing.
      - The CREW is the authority on who *belongs*. A grant row is just a row — writing
        one needs `content:write` and nothing more — so a grant on its own is an index,
        not a permission. Re-deriving membership from the crew on every action means a
        forged grant buys nothing, and that leaving or being blocked takes effect at once
        rather than at the end of whatever was already in flight.
    """
    from modules.crews import crews

    # `subject` is passed so a member of a PRIVATE cross-account crew can read it at all.
    members = set(crews.members(graph, coord["attrs"]["crew_id"], subject))
    if is_mine:
        _sync_participants(session, coord, members, source)
    if subject not in members:
        raise ValueError("not a member of this crew")
    return members


def _prune(coord: dict, members: set) -> dict:
    """Drop input from people who are no longer in the crew.

    Someone who left should not still be counted toward a quorum, so their availability
    and approval stop being persisted the next time the organiser touches the session.
    """
    a = coord["attrs"]
    patch = {}
    for field in ("weights", "approvals"):
        kept = {k: v for k, v in a.get(field, {}).items() if k in members}
        if kept != a.get(field, {}):
            patch[field] = kept
    return patch


def propose(graph: Graph, person_id: str, slots, places, owner_weights: dict | None = None,
            source: str = "coordinate") -> dict:
    session = graph.session(MODULE, SCOPES)
    person = session.get_entity(person_id)
    if person is None or person["kind"] != "person":
        raise ValueError("unknown person")
    slots = _clean_labels(slots)
    places = _clean_labels(places)
    if not slots or not places:
        raise ValueError("need at least one proposed slot and one place")

    name = person["attrs"].get("name", "friend")
    ow = _sanitize_weights(owner_weights or {"slots": {s: 1 for s in slots}}, slots, places)
    coord_id = session.create_entity("content", {
        "type": "coordination", "person_id": person_id, "person_name": name,
        "status": "awaiting_peer", "slots": slots, "places": places,
        "weights": {"owner": ow, "peer": {}}, "candidates": [],
        "approvals": {"owner": None, "peer": None}, "event_id": None, "proposed_at": _now(),
    }, source=source)

    ask = (f"Hey {name} — want to catch up? I'm free: {', '.join(slots)}. "
           f"Where works: {', '.join(places)}? Pick what suits and I'll lock it in.")
    return {"coordination_id": coord_id, "status": "awaiting_peer",
            "slots": slots, "places": places, "ask": ask}


def respond(graph: Graph, coord_id: str, peer_weights: dict | None = None,
            source: str = "coordinate") -> dict:
    session = graph.session(MODULE, SCOPES)
    coord = _load(session, coord_id)
    a = coord["attrs"]
    if a.get("status") != "awaiting_peer":
        raise ValueError(f"coordination is {a.get('status')}, not awaiting a response")

    slots, places = a["slots"], a["places"]
    peer = _sanitize_weights(peer_weights or {}, slots, places)
    candidates = core.rank_candidates({"slots": slots, "places": places}, a["weights"]["owner"], peer)
    status = "awaiting_approval" if candidates else "no_overlap"

    weights = {**a["weights"], "peer": peer}
    session.update_entity(coord_id, {"weights": weights, "candidates": candidates, "status": status},
                          source=source)
    return {"coordination_id": coord_id, "status": status, "candidates": candidates}


def approve(graph: Graph, coord_id: str, side: str, choice: int, source: str = "coordinate") -> dict:
    if side not in SIDES:
        raise ValueError("side must be 'owner' or 'peer'")
    session = graph.session(MODULE, SCOPES)
    coord = _load(session, coord_id)
    a = coord["attrs"]
    if a.get("status") not in ("awaiting_approval", "confirmed"):
        raise ValueError(f"coordination is {a.get('status')}, nothing to approve")
    candidates = a.get("candidates", [])
    if not isinstance(choice, int) or not 0 <= choice < len(candidates):
        raise ValueError("choice out of range")

    approvals = {**a.get("approvals", {}), side: choice}
    patch = {"approvals": approvals}
    result = {"coordination_id": coord_id, "approvals": approvals}

    # Both sides approved the SAME candidate -> confirm and write the meet.
    if approvals.get("owner") is not None and approvals.get("owner") == approvals.get("peer"):
        pick = candidates[choice]
        event_id = session.create_entity("event", {
            "type": "meet", "title": f"Meet {a.get('person_name', 'friend')}",
            "start": pick["slot"], "place": pick["place"], "busy": True,
            "person_id": a.get("person_id"), "source": "coordinate",
        }, source=source)
        session.create_edge(event_id, a["person_id"], "with", source=source)
        patch.update({"status": "confirmed", "event_id": event_id})
        result.update({"status": "confirmed", "event_id": event_id, "meet": pick})
    else:
        result["status"] = a.get("status")

    session.update_entity(coord_id, patch, source=source)
    return result


# ---- group (crew) coordination ---------------------------------------------


def propose_group(graph: Graph, crew_id: str, slots, places, quorum: int = 2,
                  source: str = "coordinate") -> dict:
    """Open a crew coordination. Members respond with their own availability; a night
    happens when `quorum` of them can make the same {time, place}."""
    from modules.crews import crews

    session = graph.session(MODULE, SCOPES)
    crew = crews.get(graph, crew_id)          # raises ValueError if unknown
    slots, places = _clean_labels(slots), _clean_labels(places)
    if not slots or not places:
        raise ValueError("need at least one proposed slot and one place")
    if quorum < 2:
        raise ValueError("quorum must be at least 2 (it takes two to meet)")

    coord_id = session.create_entity("content", {
        "type": "coordination", "mode": "group", "crew_id": crew_id, "crew_name": crew["name"],
        "status": "collecting", "slots": slots, "places": places, "quorum": quorum,
        "weights": {}, "candidates": [], "approvals": {}, "event_id": None,
        "confirmed": None, "proposed_at": _now(),
    }, source=source)
    participants = _sync_participants(session, session.get_entity(coord_id),
                                      set(crews.members(graph, crew_id)), source)

    ask = (f"{crew['name']} — when suits? Options: {', '.join(slots)}. "
           f"Where: {', '.join(places)}. Reply with what works and we'll take the best {quorum}+.")
    return {"coordination_id": coord_id, "status": "collecting", "crew": crew["name"],
            "member_count": crew["member_count"], "slots": slots, "places": places,
            "quorum": quorum, "participants": participants, "ask": ask}


def _rerank_group(session, coord: dict, members: set, subject: str | None, is_mine: bool,
                  source: str) -> dict:
    a = coord["attrs"]
    # Rank over CURRENT members only: whether or not the stale rows have been pruned yet,
    # a night must never be carried by someone who has left the crew.
    live = {k: v for k, v in a.get("weights", {}).items() if k in members}
    candidates = core.rank_group_candidates(
        {"slots": a["slots"], "places": a["places"]}, live, a.get("quorum", 2))
    status = "awaiting_approval" if candidates else "collecting"
    _write(session, coord["id"], {"candidates": candidates, "status": status},
           subject, is_mine, source)
    return {"coordination_id": coord["id"], "status": status, "candidates": candidates}


def respond_group(graph: Graph, coord_id: str, person_id: str, weights: dict | None = None,
                  source: str = "coordinate") -> dict:
    """One crew member submits their availability. Re-ranks after every response.

    The member may be answering from their own account, in which case the participant grant
    is both how they reach the session and the proof that they belong on it.
    """
    session = graph.session(MODULE, SCOPES)
    coord, mine = _load_shared(session, coord_id, person_id)
    a = coord["attrs"]
    if a.get("mode") != "group":
        raise ValueError("not a group coordination")
    members = _authorise(graph, session, coord, person_id, mine, source)
    if a.get("status") == "confirmed":
        raise ValueError("coordination is already confirmed")

    patch = _prune(coord, members) if mine else {}
    all_weights = {**patch.get("weights", a.get("weights", {})),
                   person_id: _sanitize_weights(weights or {}, a["slots"], a["places"])}
    _write(session, coord_id, {**patch, "weights": all_weights}, person_id, mine, source)
    coord, mine = _load_shared(session, coord_id, person_id)
    result = _rerank_group(session, coord, members, person_id, mine, source)
    result["responded"] = sorted(all_weights)
    return result


def approve_group(graph: Graph, coord_id: str, person_id: str, choice: int,
                  source: str = "coordinate") -> dict:
    """Approve a candidate. Only people who can actually make that slot count toward its
    quorum; when enough attendees approve the same option, the meet is written."""
    session = graph.session(MODULE, SCOPES)
    coord, mine = _load_shared(session, coord_id, person_id)
    a = coord["attrs"]
    if a.get("mode") != "group":
        raise ValueError("not a group coordination")
    # Authorise before anything that would leak the session's state to a non-member.
    members = _authorise(graph, session, coord, person_id, mine, source)
    if a.get("status") not in ("awaiting_approval", "confirmed"):
        raise ValueError(f"coordination is {a.get('status')}, nothing to approve")
    candidates = a.get("candidates", [])
    if not isinstance(choice, int) or not 0 <= choice < len(candidates):
        raise ValueError("choice out of range")
    pick = candidates[choice]
    if person_id not in pick["attendees"]:
        raise ValueError("you're not available for that option — respond with your times first")

    patch = _prune(coord, members) if mine else {}
    approvals = {**patch.get("approvals", a.get("approvals", {})), person_id: choice}
    backers = [pid for pid, c in approvals.items()
               if c == choice and pid in pick["attendees"] and pid in members]
    patch = {**patch, "approvals": approvals}
    result = {"coordination_id": coord_id, "approvals": approvals,
              "backers": sorted(backers), "quorum": a.get("quorum", 2), "status": a.get("status")}

    if len(backers) >= a.get("quorum", 2):
        # The outcome that everyone shares lives on the coordination; the calendar entry is
        # a local materialisation, one per graph, written by whoever wants it (see
        # add_to_calendar). Nobody writes an event into somebody else's graph.
        confirmed = {"slot": pick["slot"], "place": pick["place"],
                     "attendees": sorted(backers), "confirmed_at": _now()}
        event_id = _materialise(session, coord_id, a, confirmed, source)
        patch.update({"status": "confirmed", "confirmed": confirmed})
        if mine:
            # An id is only meaningful inside the graph that holds it, so the shared record
            # carries the organiser's calendar entry — never a participant's.
            patch["event_id"] = event_id
        result.update({"status": "confirmed", "event_id": event_id, "meet": pick})

    _write(session, coord_id, patch, person_id, mine, source)
    return result


def _materialise(session, coord_id: str, a: dict, confirmed: dict, source: str) -> str:
    """Write the confirmed crew night into THIS graph's calendar.

    `with` edges are only drawn to attendees who exist here: a fellow crew member in another
    account has no entity in your graph, and their attendance is already recorded in the
    shared `confirmed` block. A missing edge means "not someone you keep a record of",
    never "wasn't there".
    """
    event_id = session.create_entity("event", {
        "type": "meet", "title": f"{a.get('crew_name', 'Crew')} — meet",
        "start": confirmed["slot"], "place": confirmed["place"], "busy": True,
        "crew_id": a.get("crew_id"), "coordination_id": coord_id,
        "attendees": confirmed["attendees"], "source": "coordinate",
    }, source=source)
    for pid in confirmed["attendees"]:
        if session.get_entity(pid) is not None:
            session.create_edge(event_id, pid, "with", source=source)
    return event_id


def add_to_calendar(graph: Graph, coord_id: str, person_id: str,
                    source: str = "coordinate") -> dict:
    """Put a confirmed crew night on YOUR calendar, in your own graph.

    Whoever tips a session over quorum gets the event written where they are; every other
    attendee — often in a different account — asks for it here. Idempotent: calling twice
    returns the event you already have rather than duplicating the night.
    """
    session = graph.session(MODULE, SCOPES)
    coord, _mine = _load_shared(session, coord_id, person_id)
    a = coord["attrs"]
    confirmed = a.get("confirmed")
    if not confirmed:
        raise ValueError("nothing confirmed yet")
    if person_id not in confirmed.get("attendees", []):
        raise ValueError("you're not on that meet")
    existing = session.find_entities("event", {"coordination_id": coord_id}, limit=1)
    if existing:
        return {"coordination_id": coord_id, "event_id": existing[0]["id"], "added": False}
    event_id = _materialise(session, coord_id, a, confirmed, source)
    return {"coordination_id": coord_id, "event_id": event_id, "added": True}


def my_sessions(graph: Graph, person_id: str, limit: int = 50) -> list[dict]:
    """Crew sessions you can answer — including ones opened in someone else's account.

    Without this a participant would have to be handed a coordination id out of band; the
    grant already says which sessions are theirs, so it may as well be the index.
    """
    session = graph.session(MODULE, SCOPES)
    out = []
    for coord_id in session.spaces_granted(person_id, {PARTICIPANT})[:limit]:
        try:
            coord, _mine = _load_shared(session, coord_id, person_id)
        except ValueError:
            continue
        out.append(_view(coord))
    return out


def get(graph: Graph, coord_id: str, person_id: str | None = None) -> dict:
    session = graph.session(MODULE, SCOPES)
    coord, _mine = _load_shared(session, coord_id, person_id)
    return _view(coord)


def list_open(graph: Graph, limit: int = 50) -> list[dict]:
    session = graph.session(MODULE, SCOPES)
    coords = session.find_entities("content", {"type": "coordination"}, limit=limit)
    return [_view(c) for c in coords]
