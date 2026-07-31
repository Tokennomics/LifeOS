"""Crew Event Itinerary Generator.

Sequences selected venues into a structured multi-stop timeline/itinerary
for crew social events.
"""

from datetime import datetime, timedelta, timezone
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "venues"


def generate_crew_itinerary(graph: Graph, venue_ids: list[str],
                            start_time_str: str, source: str = MODULE) -> dict:
    """Generates a structured timeline itinerary from a list of venue IDs."""
    if not venue_ids:
        raise ValueError("at least one venue_id is required")

    session = graph.session(MODULE, SCOPES)
    
    # Parse start time
    try:
        current_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
    except Exception:
        current_time = datetime.now(timezone.utc)

    itinerary_stops = []

    for index, vid in enumerate(venue_ids):
        venue = session.get_entity(vid)
        if not venue or venue.get("kind") != "place":
            # Gracefully handle mock or unresolvable venues
            name = f"Placeholder Venue ({vid})"
            address = "TBD"
        else:
            attrs = venue.get("attrs", {})
            name = attrs.get("name") or attrs.get("title") or "Unnamed Venue"
            address = attrs.get("address", "")

        stop_start = current_time.isoformat()
        # Default duration: 1.5 hours per venue stop
        current_time += timedelta(hours=1, minutes=30)
        stop_end = current_time.isoformat()

        itinerary_stops.append({
            "stop_number": index + 1,
            "venue_id": vid,
            "name": name,
            "address": address,
            "start_time": stop_start,
            "end_time": stop_end
        })

        # Add 15 minutes transit buffer for next stop (if any)
        current_time += timedelta(minutes=15)

    itinerary_id = session.create_entity(
        "admin_item",
        {
            "type": "crew_itinerary",
            "stops": itinerary_stops,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        source=source
    )

    return {
        "itinerary_id": itinerary_id,
        "stops": itinerary_stops
    }
