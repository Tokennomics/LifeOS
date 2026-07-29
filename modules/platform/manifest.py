"""Developer Platform — Manifest Validation & Auto-Wiring.

Auto-wires third-party module manifests (sdk/manifest_schema.json) to
GraphSession capability scopes and token budgets.
"""

from substrate.graph import Graph, GraphSession

REQUIRED_FIELDS = ("name", "version", "scopes")


def validate_manifest(manifest_dict: dict) -> dict:
    """Validates a module manifest against developer platform schema rules."""
    if not isinstance(manifest_dict, dict):
        raise ValueError("manifest must be a JSON object")

    missing = [f for f in REQUIRED_FIELDS if f not in manifest_dict or not manifest_dict[f]]
    if missing:
        raise ValueError(f"manifest missing required fields: {missing}")

    name = str(manifest_dict["name"]).strip()
    version = str(manifest_dict["version"]).strip()
    scopes = list(manifest_dict.get("scopes", []))
    bus_topics = list(manifest_dict.get("bus_topics", []))
    token_budget = int(manifest_dict.get("token_budget", 100000))

    return {
        "valid": True,
        "name": name,
        "version": version,
        "scopes": scopes,
        "bus_topics": bus_topics,
        "token_budget": token_budget,
    }


def create_manifest_session(graph: Graph, manifest_dict: dict) -> GraphSession:
    """Spawns a GraphSession with capabilities auto-wired from the manifest."""
    val = validate_manifest(manifest_dict)
    scopes_set = set(val["scopes"])
    return graph.session(val["name"], scopes_set)
