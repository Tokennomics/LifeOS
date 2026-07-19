"""Convoy — concierge digest: what's coming up and who's in."""

from modules.convoy.events_ingest import SCOPES, upcoming
from substrate.graph import Graph

DIGEST_SYSTEM = (
    "You are a social concierge in a personal Life OS. Given upcoming social events with "
    "invite/RSVP state, write a short digest (max 90 words): what's on, who's confirmed, "
    "and the single next action per event (invite people / chase RSVPs / lock it in). "
    "Energetic but not chirpy."
)


def digest(graph: Graph, claude=None) -> dict:
    events = upcoming(graph)
    if not events:
        return {"text": "No social events on the horizon. Add one and get a crew on it.", "events": 0}
    session = graph.session("convoy", SCOPES)
    lines = []
    for ev in events:
        a = ev["attrs"]
        names = []
        for pid in a.get("yes", []):
            person = session.get_entity(pid)
            if person:
                names.append(person["attrs"].get("name", "?"))
        when = a.get("start", "")[:16].replace("T", " ")
        lines.append(f"• {a.get('title')} — {when}"
                     + (f" @ {a['place']}" if a.get("place") else "")
                     + (f" | in: {', '.join(names)}" if names else " | nobody confirmed yet"))
    text = "\n".join(lines)
    if claude is not None and claude.available:
        text = claude.complete(DIGEST_SYSTEM, text, max_tokens=1024).strip()
    return {"text": text, "events": len(events)}
