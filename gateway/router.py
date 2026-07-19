"""Intent router: free text -> module. Rule-based first (free), light Claude fallback when available."""

RULES = [
    ("horizon", ("vision", "goal", "plan my", "backcast", "this week", "priorit", "retro")),
    ("voiceos", ("capture", "note:", "remember ", "idea:")),
    ("reconnect", ("reconnect", "catch up with", "haven't seen", "message ")),
    ("convoy", ("event", "concert", "gig", "meetup", "who's in", "convoy")),
]

CLASSIFY_SYSTEM = (
    "You route a user's message to exactly one Life OS module. Modules: "
    "horizon (goals, vision, weekly planning, retros), voiceos (capture a thought/note/idea), "
    "reconnect (maintaining existing friendships), convoy (events and going out with people), "
    "chat (anything else). Respond with the routing JSON only."
)

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "module": {"type": "string", "enum": ["horizon", "voiceos", "reconnect", "convoy", "chat"]},
    },
    "required": ["module"],
    "additionalProperties": False,
}


def route(text: str, claude=None) -> dict:
    t = text.lower()
    for module, keywords in RULES:
        if any(k in t for k in keywords):
            return {"module": module, "method": "rules"}
    if claude is not None and claude.available:
        result = claude.classify(CLASSIFY_SYSTEM, text, schema=CLASSIFY_SCHEMA)
        return {"module": result["module"], "method": "claude-light"}
    return {"module": "chat", "method": "fallback"}
