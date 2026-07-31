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
