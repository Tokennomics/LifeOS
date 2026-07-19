"""VoiceOS — /capture: text (voice-note transcript or typed thought) -> content entity + extracted entities.

CLI:  python -m modules.voiceos.capture [--offline] [--config path] "the thought"
"""

import argparse
import json
import sys

from modules.voiceos import parse_to_graph
from substrate.graph import Graph

SCOPES = {
    "content:read", "content:write", "tasks:read", "tasks:write",
    "interests:read", "interests:write", "people:read", "people:write",
}


def capture(text: str, graph: Graph, claude=None, source: str = "capture") -> dict:
    session = graph.session("voiceos", SCOPES)
    capture_id = session.create_entity("content", {"type": "capture", "text": text}, source=source)
    counts = {"tasks": 0, "interests": 0, "people": 0}
    method = "raw"
    if claude is not None and claude.available:
        data = claude.complete_json(
            parse_to_graph.EXTRACT_SYSTEM, text,
            schema=parse_to_graph.EXTRACT_SCHEMA, model=claude.model_light, max_tokens=1024,
        )
        counts = parse_to_graph.apply(session, capture_id, data, source)
        method = "claude-light"
    return {"capture_id": capture_id, "method": method, **counts}


def format_summary(result: dict) -> str:
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
