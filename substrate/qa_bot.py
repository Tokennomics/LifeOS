"""Substrate Graph Memory QA Engine.

Performs queries over memory nodes to answer past event questions.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "substrate"


def query_graph_memories(graph: Graph, query_text: str) -> list[dict]:
    """Queries memory nodes matching keywords inside query_text."""
    if not query_text.strip():
        raise ValueError("query_text cannot be empty")

    session = graph.session(MODULE, SCOPES)
    memories = session.find_entities("memory", limit=1000)
    
    matches = []
    # Strip common punctuation from keywords
    cleaned_query = "".join(c if c.isalnum() or c.isspace() else " " for c in query_text)
    keywords = [w.lower().strip() for w in cleaned_query.split(" ") if len(w.strip()) > 2]

    for mem in memories:
        attrs = mem.get("attrs", {})
        text = attrs.get("text", "").lower()
        title = attrs.get("title", "").lower()
        
        # Match if any keyword is present
        score = 0
        for kw in keywords:
            if kw in text or kw in title:
                score += 1

        if score > 0 or not keywords:
            matches.append({
                "memory_id": mem["id"],
                "title": attrs.get("title", "Unnamed Memory"),
                "text": attrs.get("text", ""),
                "date": attrs.get("date", mem["created_at"][:10]),
                "relevance_score": score
            })

    # Sort descending
    matches.sort(key=lambda x: x["relevance_score"], reverse=True)
    return matches
