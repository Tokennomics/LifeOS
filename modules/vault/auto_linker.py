"""Knowledge Graph Auto-Linker.

Analyzes note entities for overlapping semantic tags and automatically creates
graph relationship edges to link related concepts.
"""

from substrate.graph import Graph

SCOPES = {"memories:read", "memories:write"}
MODULE = "vault"


def auto_link_notes(graph: Graph) -> dict:
    """Finds notes sharing 2+ tags and links them via 'feeds' edges."""
    session = graph.session(MODULE, SCOPES)
    notes = session.find_entities("memory", limit=1000)

    linked_count = 0
    # Group notes with valid tags list
    valid_notes = []
    for n in notes:
        tags = n.get("attrs", {}).get("tags", [])
        if isinstance(tags, list) and len(tags) >= 2:
            valid_notes.append((n["id"], set(t.lower().strip() for t in tags if isinstance(t, str))))

    # Scan pairs
    for i in range(len(valid_notes)):
        for j in range(i + 1, len(valid_notes)):
            id_a, tags_a = valid_notes[i]
            id_b, tags_b = valid_notes[j]

            # Intersection check
            common_tags = tags_a.intersection(tags_b)
            if len(common_tags) >= 2:
                # Check if edge already exists in either direction
                # Standard neighbor queries
                existing_a = session.neighbors(id_a, rel="feeds", direction="out")
                already_linked = any(nb["id"] == id_b for nb in existing_a)

                if not already_linked:
                    # Link from id_a to id_b
                    session.create_edge(id_a, id_b, "feeds", source=MODULE)
                    linked_count += 1

    return {
        "status": "success",
        "notes_analyzed": len(valid_notes),
        "edges_created": linked_count
    }


LINK_SYSTEM = (
    "You are an assistant in LifeOS that organizes captured thoughts by linking them to active goals. "
    "Given a list of raw capture thoughts and a list of active goals, identify which captures directly feed "
    "or contribute to which goals. Output a JSON object containing the proposed links and a short reason for each."
)

LINK_SCHEMA = {
    "type": "object",
    "properties": {
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "capture_id": {"type": "string"},
                    "goal_id": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["capture_id", "goal_id", "reason"],
                "additionalProperties": False
            }
        }
    },
    "required": ["links"],
    "additionalProperties": False
}


def auto_link_captures_to_goals(graph: Graph, claude = None) -> list[dict]:
    """Scans capture thoughts and active goals, generating link proposals (feeds relationship)."""
    session = graph.session(MODULE, {"*"})
    
    # 1. Fetch captures
    all_content = session.find_entities("content", limit=500)
    captures = []
    for item in all_content:
        attrs = item.get("attrs", {})
        # A capture has type "capture" or status "parked"/"open" (legacy/VoiceOS classification)
        if attrs.get("type") in ("capture", "thought") or "capture" in item.get("source", ""):
            # Skip if already linked to a goal
            edges = session.neighbors(item["id"], rel="feeds", direction="out")
            linked_to_goal = any(nb.get("kind") == "goal" for nb in edges)
            if not linked_to_goal:
                captures.append({
                    "id": item["id"],
                    "text": attrs.get("text") or attrs.get("title") or ""
                })
                
    # 2. Fetch goals
    goals = [{"id": g["id"], "title": g["attrs"].get("title", "")} 
             for g in session.find_entities("goal", limit=100)]
             
    if not captures or not goals:
        return []

    # 3. Try Claude if available
    if claude is not None and getattr(claude, "available", False):
        try:
            context = {
                "captures": captures,
                "goals": goals
            }
            res = claude.complete_json(LINK_SYSTEM, json.dumps(context), schema=LINK_SCHEMA)
            return res.get("links", [])
        except Exception:
            pass

    # 4. Keyword heuristic fallback
    proposals = []
    # Stop words to ignore
    stop_words = {"the", "and", "for", "with", "about", "this", "that", "from", "your", "my", "our"}
    
    for cap in captures:
        words = set(w.lower().strip(",.?!()\"'") for w in cap["text"].split())
        words = {w for w in words if len(w) > 3 and w not in stop_words}
        
        for goal in goals:
            g_words = set(w.lower().strip(",.?!()\"'") for w in goal["title"].split())
            g_words = {w for w in g_words if len(w) > 3 and w not in stop_words}
            
            overlap = words.intersection(g_words)
            if overlap:
                proposals.append({
                    "capture_id": cap["id"],
                    "capture_text": cap["text"],
                    "goal_id": goal["id"],
                    "goal_title": goal["title"],
                    "reason": f"Shared keywords: {', '.join(overlap)}"
                })
                
    return proposals


def accept_capture_link(graph: Graph, capture_id: str, goal_id: str, source: str = MODULE) -> dict:
    """Accepts a proposal and creates a feeds edge from capture to goal."""
    session = graph.session(MODULE, {"*"})
    
    # Verify entities exist
    cap = session.get_entity(capture_id)
    goal = session.get_entity(goal_id)
    if not cap or not goal:
        raise ValueError("unknown capture or goal entity")
        
    # Check if edge already exists
    existing = session.neighbors(capture_id, rel="feeds", direction="out")
    if any(nb["id"] == goal_id for nb in existing):
        return {"capture_id": capture_id, "goal_id": goal_id, "created": False}
        
    edge_id = session.create_edge(capture_id, goal_id, "feeds", source=source)
    return {"capture_id": capture_id, "goal_id": goal_id, "edge_id": edge_id, "created": True}

