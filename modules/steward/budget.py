"""Steward — Per-Module AI Token Budgeting & Rate Controller.

Tracks AI token and cost consumption per module and enforces per-run budget limits.
"""

from substrate.graph import Graph

SCOPES = {"metrics:read", "metrics:write"}


def track_tokens(graph: Graph, module: str, prompt_tokens: int, completion_tokens: int, source: str = "budget") -> dict:
    """Records token usage for a module execution."""
    session = graph.session("steward", SCOPES)
    total = max(0, prompt_tokens) + max(0, completion_tokens)
    metric_id = session.create_entity(
        "metric",
        {
            "type": "ai_usage",
            "target_module": module.strip(),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total,
        },
        source=source,
    )
    return {"metric_id": metric_id, "module": module, "total_tokens": total}


def check_budget(graph: Graph, module: str, token_limit: int = 100000) -> dict:
    """Checks if a module is within its configured token budget limit."""
    session = graph.session("steward", SCOPES)
    metrics = session.find_entities("metric", {"type": "ai_usage"}, limit=500)

    mod_metrics = [m for m in metrics if m.get("attrs", {}).get("target_module") == module]
    consumed = sum(m.get("attrs", {}).get("total_tokens", 0) for m in mod_metrics)
    within_budget = consumed < token_limit

    return {
        "module": module,
        "consumed_tokens": consumed,
        "token_limit": token_limit,
        "remaining_tokens": max(0, token_limit - consumed),
        "within_budget": within_budget,
    }
