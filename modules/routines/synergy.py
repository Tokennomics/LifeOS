"""Habit Synergy Analyzer.

Measures correlation statistics across multiple habit and routine logs.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "routines"


def calculate_habit_synergies(graph: Graph) -> list[dict]:
    """Computes correlation percentages between sleep habits and focus quality."""
    session = graph.session(MODULE, SCOPES)
    
    metrics = session.find_entities("metric", limit=1000)
    
    focus_days = set()
    sleep_days = {}

    for item in metrics:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "focus_session":
            # Assume date from created_at or timestamp
            day = item["created_at"][:10]
            focus_days.add(day)
        elif attrs.get("type") == "sleep_record":
            day = attrs.get("date", "")
            quality = attrs.get("sleep_quality", 0)
            if day:
                sleep_days[day] = quality

    if not sleep_days or not focus_days:
        return [
            {
                "habit_a": "High Sleep Quality (>=7)",
                "habit_b": "Mindful Focus Completion",
                "synergy_score": 0.0,
                "notes": "Insufficient overlapping habit log data to analyze synergies yet."
            }
        ]

    # Calculate overlaps
    high_sleep_days = {d for d, q in sleep_days.items() if q >= 7}
    overlapping_focus = focus_days.intersection(high_sleep_days)

    synergy = (len(overlapping_focus) / len(high_sleep_days)) * 100.0 if high_sleep_days else 0.0

    return [
        {
            "habit_a": "High Sleep Quality (>=7)",
            "habit_b": "Mindful Focus Completion",
            "synergy_score": round(synergy, 1),
            "notes": f"Completed focus sessions on {len(overlapping_focus)} out of {len(high_sleep_days)} high-sleep days."
        }
    ]
