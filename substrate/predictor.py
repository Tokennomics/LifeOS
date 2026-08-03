"""Graph Relationship Link Predictor.

Analyzes interest nodes to predict candidate relations across the graph network.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def predict_relationships(graph: Graph) -> list[dict]:
    """Generates suggested relationships based on overlapping interest nodes."""
    session = graph.session(MODULE, SCOPES)
    
    people = session.find_entities("person", limit=100)
    interests = session.find_entities("interest", limit=100)

    # Map people to their interested_in node relations
    person_interests = {}
    for p in people:
        p_interests = []
        # Find neighbors
        try:
            neighbors = session.neighbors(p["id"], rel="interested_in")
            p_interests = [n["id"] for n in neighbors]
        except Exception:
            pass
        person_interests[p["id"]] = p_interests

    suggestions = []
    # Find matching interest pairs
    processed = set()
    for p1_id, p1_interests in person_interests.items():
        for p2_id, p2_interests in person_interests.items():
            if p1_id == p2_id:
                continue
            pair = tuple(sorted([p1_id, p2_id]))
            if pair in processed:
                continue
            processed.add(pair)

            shared = set(p1_interests).intersection(set(p2_interests))
            if shared:
                # Suggest they connect
                name1 = next((p["attrs"].get("name", "?") for p in people if p["id"] == p1_id), "?")
                name2 = next((p["attrs"].get("name", "?") for p in people if p["id"] == p2_id), "?")
                suggestions.append({
                    "src_id": p1_id,
                    "dst_id": p2_id,
                    "src_name": name1,
                    "dst_name": name2,
                    "shared_interests_count": len(shared),
                    "relationship_type_suggested": "with",
                    "reason": f"Both {name1} and {name2} share interests in {[next((i['attrs'].get('name', '?') for i in interests if i['id'] == sid), '?') for sid in shared]}."
                })

    return suggestions
