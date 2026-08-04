"""Outing Schedule Matcher.

Matches availability schedules across crew members to find optimal outing times.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "venues"


def match_outing_slots(
    graph: Graph,
    member_ids: list[str],
    day: str
) -> list[str]:
    """Intersects availability hours across crew members to recommend outing slots."""
    if not member_ids:
        raise ValueError("member_ids list cannot be empty")
    if not day.strip():
        raise ValueError("day is required")

    session = graph.session(MODULE, SCOPES)
    
    # Query metric entities containing calendars
    metrics = session.find_entities("metric", limit=1000)
    
    # Hour slots from 09:00 to 22:00
    all_slots = {f"{h:02d}:00" for h in range(9, 23)}

    member_busy = {m: set() for m in member_ids}

    for item in metrics:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "calendar_event" and attrs.get("date") == day:
            owner = attrs.get("owner_id")
            if owner in member_busy:
                slot = attrs.get("time_slot")
                if slot:
                    member_busy[owner].add(slot)

    # Intersect free slots
    free_slots = set(all_slots)
    for m in member_ids:
        busy = member_busy[m]
        free_slots = free_slots - busy

    # Return sorted slots
    return sorted(list(free_slots))
