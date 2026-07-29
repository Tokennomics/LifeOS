"""Personal Knowledge Vault & Semantic Memory Recall.

Stores book insights, key takeaways, and research notes as structured memory nodes
with concept tags for instant retrieval during goal planning or crew events.
"""

from substrate.graph import Graph

SCOPES = {"memories:read", "memories:write"}
MODULE = "vault"


def save_note(graph: Graph, title: str, content: str, tags: list[str] | None = None,
              source: str = MODULE) -> dict:
    """Saves a knowledge note to the vault."""
    if not title.strip():
        raise ValueError("note title required")

    tags_clean = [t.strip().lower() for t in (tags or []) if t.strip()]

    session = graph.session(MODULE, SCOPES)
    note_id = session.create_entity(
        "memory",
        {
            "type": "knowledge_note",
            "title": title.strip(),
            "content": content.strip(),
            "tags": tags_clean,
        },
        source=source,
    )
    return {"note_id": note_id, "title": title, "tags": tags_clean}


def search_vault(graph: Graph, query: str = "", tag: str = "") -> list[dict]:
    """Searches knowledge notes in the vault by query or tag."""
    session = graph.session(MODULE, SCOPES)
    notes = session.find_entities("memory", {"type": "knowledge_note"}, limit=200)

    q_lower = query.lower().strip()
    t_lower = tag.lower().strip()

    res = []
    for n in notes:
        attrs = n.get("attrs", {})
        title = attrs.get("title", "")
        content = attrs.get("content", "")
        n_tags = attrs.get("tags", [])

        match_q = not q_lower or (q_lower in title.lower() or q_lower in content.lower() or any(q_lower in t.lower() for t in n_tags))
        match_t = not t_lower or any(t_lower == t.lower() for t in n_tags)

        if match_q and match_t:
            res.append({
                "note_id": n["id"],
                "title": title,
                "content": content,
                "tags": n_tags,
                "created_at": n.get("created_at", ""),
            })

    return res
