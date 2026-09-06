"""Personalized Event Recommendation Feed Engine.

Ranks and recommends upcoming events based on logged user interests.
"""

from substrate.graph import Graph

SCOPES = {"events:read", "interests:read"}
MODULE = "venues"


def get_personalized_event_feed(graph: Graph) -> list[dict]:
    """Scores, ranks, and returns recommended events based on user interests."""
    session = graph.session(MODULE, SCOPES)
    
    interests = session.find_entities("interest", limit=200)
    events = session.find_entities("event", limit=200)

    interest_words = set()
    for inst in interests:
        name = inst.get("attrs", {}).get("name", "").lower().strip()
        if name:
            interest_words.add(name)

    feed = []

    for ev in events:
        attrs = ev.get("attrs", {})
        title = attrs.get("title", "Unnamed Event")
        topic = attrs.get("topic", "").lower().strip()
        description = attrs.get("description", "").lower().strip()
        place = attrs.get("place", "")

        # Compute match score based on keyword overlap
        score = 1.0
        matches = []

        for w in interest_words:
            if w in topic or w in description or w in title.lower():
                score += 3.0
                matches.append(w)

        feed.append({
            "event_id": ev["id"],
            "title": title,
            "topic": attrs.get("topic", "General"),
            "place": place,
            "matched_interests": matches,
            "match_count": len(matches),
            "_rank": score,
            "start": attrs.get("start", "")
        })

    # The score orders the list and does not leave this function. It was reported as
    # `match_score`: a number built as 3.0 per keyword hit, which reads to a user as a
    # measured affinity and is nothing of the kind — `matched_interests` is the same
    # information, checkable, and says *why* a thing ranked where it did. Same reasoning as
    # `modules/city/synergy.py`, which reports shared terms rather than a percentage.
    feed.sort(key=lambda item: (-item["_rank"], item["title"]))
    for item in feed:
        item.pop("_rank", None)
    return feed
