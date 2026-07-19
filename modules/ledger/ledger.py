"""Ledger — goals-integrated money, P0: friction-free spend log + monthly shape."""

import datetime

from substrate.graph import Graph

SCOPES = {"metrics:read", "metrics:write"}


def _month(now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m")


def log_spend(graph: Graph, amount: float, category: str, note: str = "",
              source: str = "ledger") -> str:
    if amount <= 0:
        raise ValueError("amount must be positive")
    session = graph.session("ledger", SCOPES)
    return session.create_entity(
        "metric",
        {"type": "spend", "amount": round(float(amount), 2), "category": category.strip().lower() or "misc",
         "note": note, "month": _month()},
        source=source,
    )


def summary(graph: Graph, month: str | None = None) -> dict:
    month = month or _month()
    session = graph.session("ledger", SCOPES)
    by_category: dict[str, float] = {}
    count = 0
    for spend in session.find_entities("metric", {"type": "spend", "month": month}, limit=500):
        a = spend["attrs"]
        by_category[a.get("category", "misc")] = round(
            by_category.get(a.get("category", "misc"), 0.0) + a.get("amount", 0.0), 2)
        count += 1
    return {"month": month, "count": count,
            "total": round(sum(by_category.values()), 2),
            "by_category": dict(sorted(by_category.items(), key=lambda kv: kv[1], reverse=True))}
