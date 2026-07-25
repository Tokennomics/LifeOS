"""Coordinate — the pure ranking engine (no graph, no I/O, deterministic).

Contract:
  proposal      = {"slots": [iso_str, ...], "places": [str, ...]}
  weights_a/b   = {"slots": {slot: weight}, "places": {place: weight}}
                  slot  weight > 0  => that person is available then (higher = preferred);
                                       absent/<=0 => not available.
                  place weight       defaults to 1 (fine); 0 => vetoed.

rank_candidates returns the ranked common options, most-preferred first:
  [{"slot", "place", "score", "slot_score", "place_score"}, ...]
Empty list means no overlap (no time or no place both accept). Ties break by earliest
slot time then place name, so the result is stable for the golden/repeatable tests.

Privacy: the engine only ever sees weights over the *proposed* slots/places — never a
calendar. Each party derives its vector locally and shares just that.
"""


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def rank_group_candidates(proposal: dict, participant_weights: dict, quorum: int = 2,
                          limit: int = 3) -> list[dict]:
    """Rank {time, place} for a CREW (N people). The 1:1 case is this with quorum=2 and
    everyone required; groups differ in two deliberate ways:

      - **Quorum, not unanimity.** A crew night happens when enough people can make it.
        A candidate needs >= quorum attendees; more attendees beats mild preference.
      - **Place is chosen per slot, among that slot's attendees.** A venue vetoed by
        someone who can't come that night shouldn't block the night.

    participant_weights = {participant_id: {"slots": {...}, "places": {...}}}
    Returns [{"slot", "place", "attendees": [ids], "attendee_count", "score", ...}], best
    first, ordered by attendee_count desc, then score desc, then earliest slot.
    """
    slots = proposal.get("slots", [])
    places = proposal.get("places", [])
    if not slots or not places or not participant_weights:
        return []

    out = []
    for slot in slots:
        attendees = [pid for pid, w in participant_weights.items()
                     if _num((w or {}).get("slots", {}).get(slot)) > 0]
        if len(attendees) < quorum:
            continue
        slot_score = sum(_num(participant_weights[pid].get("slots", {}).get(slot)) for pid in attendees)

        # Best place among those no ATTENDEE vetoes (absent weight = fine = 1).
        ranked_places = []
        for place in places:
            weights = [_num((participant_weights[pid] or {}).get("places", {}).get(place, 1))
                       for pid in attendees]
            if any(w <= 0 for w in weights):
                continue
            ranked_places.append((place, sum(weights)))
        if not ranked_places:
            continue
        ranked_places.sort(key=lambda x: (-x[1], x[0]))
        place, place_score = ranked_places[0]

        out.append({"slot": slot, "place": place, "attendees": sorted(attendees),
                    "attendee_count": len(attendees), "score": slot_score + place_score,
                    "slot_score": slot_score, "place_score": place_score})

    # More of the crew there wins; then preference; then earliest.
    out.sort(key=lambda c: (-c["attendee_count"], -c["score"], c["slot"]))
    return out[:max(0, limit)]


def rank_candidates(proposal: dict, weights_a: dict, weights_b: dict, limit: int = 3) -> list[dict]:
    slots = proposal.get("slots", [])
    places = proposal.get("places", [])
    sa, sb = weights_a.get("slots", {}), weights_b.get("slots", {})
    pa, pb = weights_a.get("places", {}), weights_b.get("places", {})

    # A slot counts only if BOTH are available; its score is the summed preference.
    common_slots = [(s, _num(sa.get(s)) + _num(sb.get(s)))
                    for s in slots if _num(sa.get(s)) > 0 and _num(sb.get(s)) > 0]
    # Places default to 1 (fine); a 0 weight is a veto.
    common_places = [(p, _num(pa.get(p, 1)) + _num(pb.get(p, 1)))
                     for p in places if _num(pa.get(p, 1)) > 0 and _num(pb.get(p, 1)) > 0]
    if not common_slots or not common_places:
        return []

    common_places.sort(key=lambda x: (-x[1], x[0]))
    best_place, place_score = common_places[0]
    common_slots.sort(key=lambda x: (-x[1], x[0]))  # preference desc, then earliest time

    return [
        {"slot": s, "place": best_place, "score": ss + place_score,
         "slot_score": ss, "place_score": place_score}
        for s, ss in common_slots[:max(0, limit)]
    ]
