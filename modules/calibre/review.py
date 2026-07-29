"""Calibre — Decision Outcome Reviews & Calibration.

Systematic review workflow to evaluate predicted decision outcomes vs reality
and sharpen judgment calibration.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"decisions:read", "decisions:write", "metrics:read", "metrics:write"}


def pending_reviews(graph: Graph) -> list[dict]:
    """Lists unresolved decisions whose review period has elapsed."""
    session = graph.session("calibre", SCOPES)
    now = datetime.now(timezone.utc)
    out = []

    for d in session.find_entities("decision", limit=200):
        attrs = d.get("attrs", {})
        if attrs.get("status") == "resolved":
            continue

        review_days = attrs.get("review_days", 30)
        created_at_str = d.get("created_at", "")

        try:
            created_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            days_elapsed = (now - created_dt).total_seconds() / 86400.0
        except (ValueError, TypeError):
            days_elapsed = 0.0

        review_at_str = attrs.get("review_at", "")
        if review_at_str:
            is_due = review_at_str <= now.isoformat()
        else:
            is_due = days_elapsed >= review_days
        out.append({
            "id": d["id"],
            "title": attrs.get("title", ""),
            "choice": attrs.get("choice", ""),
            "confidence": attrs.get("confidence", 0.5),
            "predicted": attrs.get("predicted", ""),
            "days_elapsed": round(days_elapsed, 1),
            "review_days": review_days,
            "due_for_review": is_due,
        })

    out.sort(key=lambda item: (-item["due_for_review"], -item["days_elapsed"]))
    return out


def record_outcome(graph: Graph, decision_id: str, happened: bool, reflection: str = "", source: str = "calibre") -> dict:
    """Evaluates a decision prediction vs reality and records calibration metric."""
    session = graph.session("calibre", SCOPES)
    decision = session.get_entity(decision_id)
    if decision is None or decision["kind"] != "decision":
        raise ValueError(f"Decision entity not found: {decision_id}")

    attrs = decision.get("attrs", {})
    confidence = attrs.get("confidence", 0.5)
    
    # Calculate calibration error: confidence (0.0-1.0) vs actual (1.0 or 0.0)
    actual_val = 1.0 if happened else 0.0
    calibration_error = round(abs(confidence - actual_val), 2)

    updated_attrs = {
        "status": "resolved",
        "happened": happened,
        "reflection": reflection.strip(),
        "calibration_error": calibration_error,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    session.update_entity(decision_id, updated_attrs, source=source)

    # Record calibration metric observation
    session.create_entity(
        "metric",
        {
            "type": "decision_calibration",
            "decision_id": decision_id,
            "confidence": confidence,
            "happened": happened,
            "error": calibration_error,
        },
        source=source,
    )

    return {
        "decision_id": decision_id,
        "status": "resolved",
        "happened": happened,
        "calibration_error": calibration_error,
        "reflection": reflection.strip(),
    }
