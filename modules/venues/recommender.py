"""Smart Place & Venue Recommendation Engine.

Recommends local places to crews or users based on overlapping interests,
past attendance, and match score metrics.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "venues"


def recommend_places(graph: Graph, crew_id: str | None = None) -> list[dict]:
    """Recommends places ranked by interest and category matches."""
    session = graph.session(MODULE, SCOPES)
    
    places = session.find_entities("place", limit=200)
    interests = session.find_entities("interest", limit=200)

    # Compile a set of interest names/categories to rank matching venues
    interest_keywords = set()
    for inst in interests:
        name = inst.get("attrs", {}).get("name", "").lower().strip()
        if name:
            interest_keywords.add(name)

    recommendations = []

    for p in places:
        attrs = p.get("attrs", {})
        p_name = attrs.get("name") or attrs.get("title") or "Unnamed Place"
        p_category = attrs.get("category", "").lower().strip()
        p_description = attrs.get("description", "").lower().strip()

        # Compute match score based on keyword overlap
        score = 1.0  # Base score
        matches = []

        for kw in interest_keywords:
            if kw in p_category or kw in p_description or kw in p_name.lower():
                score += 2.0
                matches.append(kw)

        recommendations.append({
            "place_id": p["id"],
            "name": p_name,
            "category": attrs.get("category", "General"),
            "match_score": score,
            "matched_interests": matches,
            "address": attrs.get("address", "")
        })

    # Sort by match score descending
    recommendations.sort(key=lambda x: x["match_score"], reverse=True)
    return recommendations
