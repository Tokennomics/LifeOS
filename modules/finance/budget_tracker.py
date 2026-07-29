"""Personal Financial Goal & Budget Tracker.

Links monetary goals (runway, travel budget, savings targets) directly
to 12-week Horizon goals and tracks completion progress.
"""

from substrate.graph import Graph

SCOPES = {"goals:read", "goals:write"}
MODULE = "finance"


def create_financial_goal(graph: Graph, title: str, target_amount: float,
                          current_amount: float = 0.0, currency: str = "USD",
                          source: str = MODULE) -> dict:
    """Creates a financial goal entity in the graph."""
    if not title.strip():
        raise ValueError("financial goal title required")
    if target_amount <= 0:
        raise ValueError("target_amount must be positive")

    session = graph.session(MODULE, SCOPES)
    goal_id = session.create_entity(
        "goal",
        {
            "type": "financial_goal",
            "title": title.strip(),
            "target_amount": float(target_amount),
            "current_amount": float(current_amount),
            "currency": currency.upper().strip(),
            "focus": True,
        },
        source=source,
    )
    pct = round((current_amount / target_amount) * 100.0, 1)
    return {
        "financial_goal_id": goal_id,
        "title": title,
        "target_amount": target_amount,
        "current_amount": current_amount,
        "currency": currency,
        "completion_percentage": min(pct, 100.0),
    }


def log_financial_progress(graph: Graph, goal_id: str, amount_delta: float,
                           source: str = MODULE) -> dict:
    """Logs progress towards a financial goal."""
    session = graph.session(MODULE, SCOPES)
    entity = session.get_entity(goal_id)
    if not entity or entity.get("kind") != "goal" or entity.get("attrs", {}).get("type") != "financial_goal":
        raise ValueError(f"financial goal '{goal_id}' not found")

    attrs = entity.get("attrs", {})
    curr = attrs.get("current_amount", 0.0) + float(amount_delta)
    target = attrs.get("target_amount", 1.0)

    attrs["current_amount"] = curr
    session.update_entity(goal_id, attrs, source=source)

    pct = round((curr / target) * 100.0, 1)
    return {
        "financial_goal_id": goal_id,
        "title": attrs.get("title"),
        "target_amount": target,
        "current_amount": curr,
        "completion_percentage": min(pct, 100.0),
    }


def get_financial_summary(graph: Graph) -> dict:
    """Generates financial goals summary metrics."""
    session = graph.session(MODULE, SCOPES)
    goals = session.find_entities("goal", {"type": "financial_goal"}, limit=100)

    items = []
    tot_target = 0.0
    tot_current = 0.0

    for g in goals:
        attrs = g.get("attrs", {})
        target = attrs.get("target_amount", 0.0)
        curr = attrs.get("current_amount", 0.0)
        tot_target += target
        tot_current += curr
        pct = round((curr / target) * 100.0, 1) if target > 0 else 0.0
        items.append({
            "financial_goal_id": g["id"],
            "title": attrs.get("title", ""),
            "target_amount": target,
            "current_amount": curr,
            "currency": attrs.get("currency", "USD"),
            "completion_percentage": min(pct, 100.0),
        })

    overall_pct = round((tot_current / tot_target) * 100.0, 1) if tot_target > 0 else 0.0

    return {
        "financial_goals_count": len(items),
        "total_target_amount": tot_target,
        "total_current_amount": tot_current,
        "overall_completion_percentage": min(overall_pct, 100.0),
        "goals": items,
    }
