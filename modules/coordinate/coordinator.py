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
"""

import datetime

from modules.coordinate import core
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "people:read", "events:read", "events:write"}
MODULE = "coordinate"
SIDES = ("owner", "peer")


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
    return {"id": coord["id"], "person_id": a.get("person_id"), "person_name": a.get("person_name"),
            "status": a.get("status"), "slots": a.get("slots", []), "places": a.get("places", []),
            "candidates": a.get("candidates", []), "approvals": a.get("approvals", {}),
            "event_id": a.get("event_id")}


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


def get(graph: Graph, coord_id: str) -> dict:
    session = graph.session(MODULE, SCOPES)
    return _view(_load(session, coord_id))


def list_open(graph: Graph, limit: int = 50) -> list[dict]:
    session = graph.session(MODULE, SCOPES)
    coords = session.find_entities("content", {"type": "coordination"}, limit=limit)
    return [_view(c) for c in coords]
