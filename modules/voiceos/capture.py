"""VoiceOS — /capture: text (voice-note transcript or typed thought) -> content entity + extracted entities.

CLI:  python -m modules.voiceos.capture [--offline] [--config path] "the thought"
"""

import argparse
import json
import sys

from modules.horizon import core
from modules.voiceos import parse_to_graph
from substrate import now_iso
from substrate.graph import Graph

SCOPES = {
    "content:read", "content:write", "tasks:read", "tasks:write",
    "interests:read", "interests:write", "people:read", "people:write",
}


def capture(text: str, graph: Graph, claude=None, source: str = "capture") -> dict:
    session = graph.session("voiceos", SCOPES)
    counts = {"tasks": 0, "interests": 0, "people": 0}

    # Distraction sink (T3): a new-project idea is parked, not planned — it stays
    # captured so nothing is lost, but the current gate keeps priority.
    if core.is_project_idea(text):
        pid = session.create_entity(
            "content", {"type": "parked_idea", "text": text, "parked_at": now_iso()}, source=source,
        )
        return {"capture_id": pid, "method": "parked", "parked": True,
                "message": core.PARK_MESSAGE, **counts}

    capture_id = session.create_entity("content", {"type": "capture", "text": text}, source=source)
    method = "raw"
    if claude is not None and claude.available:
        data = claude.complete_json(
            parse_to_graph.EXTRACT_SYSTEM, text,
            schema=parse_to_graph.EXTRACT_SCHEMA, model=claude.model_light, max_tokens=1024,
        )
        counts = parse_to_graph.apply(session, capture_id, data, source)
        method = "claude-light"
    return {"capture_id": capture_id, "method": method, "parked": False, **counts}


def list_parked(graph: Graph) -> list[dict]:
    """The distraction sink's contents — captured, not abandoned."""
    session = graph.session("voiceos", SCOPES)
    parked = session.find_entities("content", {"type": "parked_idea"}, limit=200)
    return [{"id": p["id"], "text": p["attrs"].get("text", ""),
             "parked_at": p["attrs"].get("parked_at", "")} for p in parked]


def format_summary(result: dict) -> str:
    if result.get("parked"):
        return result["message"]
    extracted = ", ".join(f"{v} {k}" for k, v in result.items() if k in ("tasks", "interests", "people") and v)
    return f"Captured. Extracted: {extracted}." if extracted else "Captured."


def main():
    from gateway.claude import ClaudeGateway
    from substrate import load_config
    from substrate.migrate import migrate

    parser = argparse.ArgumentParser(description="VoiceOS capture")
    parser.add_argument("text", nargs="?")
    parser.add_argument("--config", default=None)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    text = args.text or sys.stdin.read()
    if not text.strip():
        sys.exit("Nothing to capture.")
    cfg = load_config(args.config)
    graph = Graph(migrate(cfg), default_owner=cfg.get("owner", {}).get("id"))
    claude = None if args.offline else ClaudeGateway(cfg)
    result = capture(text, graph, claude=claude)
    print(json.dumps(result))
    print(format_summary(result))


if __name__ == "__main__":
    main()
