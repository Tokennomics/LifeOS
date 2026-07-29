"""Personal Reflection & Gratitude Journal.

Micro-gratitude logger, daily wins tracker, and mood monitor linked to
memories and weekly retros.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"memories:read", "memories:write"}
MODULE = "memento"


def log_journal_entry(graph: Graph, wins: list[str] | None = None,
                      gratitude: list[str] | None = None, reflection: str = "",
                      mood_rating: int = 5, source: str = MODULE) -> dict:
    """Logs a daily reflection and gratitude journal entry."""
    now_iso = datetime.now(timezone.utc).isoformat()
    session = graph.session(MODULE, SCOPES)
    entry_id = session.create_entity(
        "memory",
        {
            "type": "journal_entry",
            "wins": wins or [],
            "gratitude": gratitude or [],
            "reflection": reflection.strip(),
            "mood_rating": max(1, min(10, int(mood_rating))),
            "timestamp": now_iso,
        },
        source=source,
    )
    return {"entry_id": entry_id, "timestamp": now_iso, "mood_rating": mood_rating}


def get_journal_entries(graph: Graph, limit: int = 50) -> list[dict]:
    """Retrieves journal entry memories."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("memory", {"type": "journal_entry"}, limit=limit)

    res = []
    for item in items:
        attrs = item.get("attrs", {})
        res.append({
            "entry_id": item["id"],
            "wins": attrs.get("wins", []),
            "gratitude": attrs.get("gratitude", []),
            "reflection": attrs.get("reflection", ""),
            "mood_rating": attrs.get("mood_rating", 5),
            "timestamp": attrs.get("timestamp", ""),
        })

    return res
