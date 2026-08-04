"""Local Interest Recommendation Finder.

Recommends nearby places matching the user's active interests.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "venues"


def recommend_local_interests(
    graph: Graph,
    lat: float,
    lon: float
) -> list[dict]:
    """Recommends local venues matching user interest keywords."""
    session = graph.session(MODULE, SCOPES)
    
    # Get user interests
    interest_entities = session.find_entities("interest", limit=100)
    interests = {ent.get("attrs", {}).get("name", "").lower() for ent in interest_entities if ent.get("attrs", {}).get("name")}
    
    # If no interest nodes in graph, default to standard high-value interests
    if not interests:
        interests = {"coffee", "climbing", "hiking", "fitness", "nature"}

    # Get local venues
    places = session.find_entities("place", limit=500)
    recs = []
    
    for pl in places:
        attrs = pl.get("attrs", {})
        p_lat = attrs.get("lat")
        p_lon = attrs.get("lon")
        name = attrs.get("name", "")
        
        # Simple coordinate proximity checker
        if p_lat is not None and p_lon is not None:
            if abs(p_lat - lat) < 0.15 and abs(p_lon - lon) < 0.15:
                # Find matching interests in name
                matching = [it for it in interests if it in name.lower()]
                recs.append({
                    "place_id": pl["id"],
                    "name": name,
                    "lat": p_lat,
                    "lon": p_lon,
                    "matching_interests": matching,
                    "score": len(matching) * 10 + 5
                })

    # Sort by recommendation score
    recs.sort(key=lambda x: x["score"], reverse=True)
    return recs
