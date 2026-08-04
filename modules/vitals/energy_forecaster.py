"""Circadian Energy Budget Forecaster.

Predicts body battery energy index metrics based on sleep trend data.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "vitals"


def forecast_energy_battery(graph: Graph) -> dict:
    """Predicts body battery level based on sleep quality history."""
    session = graph.session(MODULE, SCOPES)
    
    metrics = session.find_entities("metric", limit=50)
    sleep_records = [m for m in metrics if m.get("attrs", {}).get("type") == "sleep_record"]

    if not sleep_records:
        return {
            "predicted_body_battery": 75,
            "status": "baseline",
            "message": "No sleep records found. Returning baseline level."
        }

    # Fetch average sleep quality
    total_quality = 0
    for r in sleep_records:
        total_quality += r.get("attrs", {}).get("sleep_quality", 5)
    avg_quality = total_quality / len(sleep_records)

    battery = int(avg_quality * 10)
    # Clamp to [10, 100]
    battery = max(10, min(100, battery))

    return {
        "predicted_body_battery": battery,
        "status": "charged" if battery >= 75 else "drained",
        "message": f"Based on sleep quality average of {round(avg_quality, 1)}/10, your predicted body battery is {battery}%."
    }
