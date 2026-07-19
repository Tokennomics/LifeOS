"""Calibre — decision journal with calibration scoring (Brier). Native to a quant's worldview.

Log the decision + a probability that the predicted outcome happens; resolve it later;
brier = (confidence - outcome)^2, lower is better (0.25 = coin-flip calibration).
"""

import datetime

from substrate.graph import Graph

SCOPES = {"decisions:read", "decisions:write", "metrics:read", "metrics:write"}


def log(graph: Graph, title: str, choice: str, confidence: float, predicted: str,
        review_days: int = 30, source: str = "calibre") -> str:
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")
    session = graph.session("calibre", SCOPES)
    review_at = (datetime.datetime.now(datetime.timezone.utc)
                 + datetime.timedelta(days=review_days)).isoformat()
    return session.create_entity(
        "decision",
        {"title": title, "choice": choice, "confidence": round(confidence, 2),
         "predicted": predicted, "status": "open", "review_at": review_at},
        source=source,
    )


def open_decisions(graph: Graph) -> list[dict]:
    session = graph.session("calibre", SCOPES)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = []
    for decision in session.find_entities("decision", {"status": "open"}, limit=100):
        a = decision["attrs"]
        out.append({"id": decision["id"], "title": a.get("title", ""), "choice": a.get("choice", ""),
                    "confidence": a.get("confidence", 0.5), "predicted": a.get("predicted", ""),
                    "review_at": a.get("review_at", ""), "due": a.get("review_at", "") <= now})
    out.sort(key=lambda d: d["review_at"])
    return out


def resolve(graph: Graph, decision_id: str, happened: bool, source: str = "calibre") -> dict:
    session = graph.session("calibre", SCOPES)
    decision = session.get_entity(decision_id)
    if decision is None or decision["kind"] != "decision":
        raise ValueError("unknown decision")
    confidence = decision["attrs"].get("confidence", 0.5)
    brier = round((confidence - (1.0 if happened else 0.0)) ** 2, 4)
    session.update_entity(decision_id, {"status": "resolved", "happened": happened, "brier": brier},
                          source=source)
    session.create_entity("metric", {"type": "calibration", "brier": brier}, source=source)
    return {"decision_id": decision_id, "brier": brier}


def calibration(graph: Graph) -> dict:
    session = graph.session("calibre", SCOPES)
    briers = [m["attrs"].get("brier", 0.0)
              for m in session.find_entities("metric", {"type": "calibration"}, limit=500)]
    return {"n": len(briers),
            "avg_brier": round(sum(briers) / len(briers), 4) if briers else None}
