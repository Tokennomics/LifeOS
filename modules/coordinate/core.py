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
