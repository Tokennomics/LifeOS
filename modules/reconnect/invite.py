"""Reconnect — one-tap invite drafts (execution, not reminders)."""

from modules.reconnect.decay import SCOPES
from substrate.graph import Graph

INVITE_SYSTEM = (
    "You draft a short, warm reconnect message to a friend the user hasn't seen in a while. "
    "Sound like a normal text from a friend: no guilt, no 'it's been ages' apology spiral, "
    "one concrete low-pressure suggestion (walk, coffee, call) with two time options. "
    "Under 45 words. Return only the message text."
)


def draft(graph: Graph, person_id: str, claude=None) -> dict:
    session = graph.session("reconnect", SCOPES)
    person = session.get_entity(person_id)
    if person is None or person["kind"] != "person":
        raise ValueError("unknown person")
    name = person["attrs"].get("name", "friend")
    if claude is not None and claude.available:
        text = claude.complete(INVITE_SYSTEM, f"Friend's name: {name}", max_tokens=512).strip()
        method = "claude"
    else:
        text = (f"Hey {name} — you crossed my mind today. Fancy a walk or a coffee this week? "
                f"I'm free Tuesday or Thursday evening.")
        method = "offline"
    return {"person_id": person_id, "name": name, "text": text, "method": method}
