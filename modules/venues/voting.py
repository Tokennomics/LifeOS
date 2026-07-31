"""Crew Venue Voting Engine.

Tracks venue votes for outings and aggregates poll results.
"""

from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write"}
MODULE = "venues"


def submit_vote(
    graph: Graph,
    poll_id: str,
    place_id: str,
    member_id: str
) -> dict:
    """Submits a member's vote for a place in a specific poll."""
    if not poll_id.strip() or not place_id.strip() or not member_id.strip():
        raise ValueError("poll_id, place_id, and member_id are required")

    session = graph.session(MODULE, SCOPES)
    
    # Store vote as an admin_item
    attrs = {
        "type": "venue_vote",
        "poll_id": poll_id,
        "place_id": place_id,
        "member_id": member_id
    }
    
    # In a real app we might update if a vote already exists,
    # but for simplicity we append and count unique.
    vote_id = session.create_entity("admin_item", attrs, source="venue_voting")
    return {
        "vote_id": vote_id,
        "poll_id": poll_id,
        "place_id": place_id,
        "member_id": member_id,
        "status": "Vote recorded."
    }


def get_poll_results(graph: Graph, poll_id: str) -> dict:
    """Aggregates all votes for a poll and returns place ranking details."""
    session = graph.session(MODULE, SCOPES)
    
    items = session.find_entities("admin_item", limit=1000)
    
    votes_by_place = {}
    voted_members = set()

    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "venue_vote" and attrs.get("poll_id") == poll_id:
            m_id = attrs.get("member_id")
            p_id = attrs.get("place_id")
            # Only count the latest vote per member
            if m_id not in voted_members:
                voted_members.add(m_id)
                votes_by_place[p_id] = votes_by_place.get(p_id, 0) + 1

    sorted_results = sorted(
        [{"place_id": p, "votes": count} for p, count in votes_by_place.items()],
        key=lambda x: x["votes"],
        reverse=True
    )

    winner = sorted_results[0]["place_id"] if sorted_results else "None"

    return {
        "poll_id": poll_id,
        "total_votes": len(voted_members),
        "results": sorted_results,
        "winner_place_id": winner
    }
