"""AI Life Assistant — Context-Aware Conversational Gateway.

Reads current LifeOS graph context (goals, tasks, energy baselines, triage brief)
to answer natural language queries and suggest high-leverage focus actions.
"""

from modules.horizon import energy_balance, planner
from modules.triage import brief
from substrate.graph import Graph


def process_assistant_message(graph: Graph, message: str, claude=None) -> dict:
    """Processes natural language chat message using live graph context."""
    if not message.strip():
        raise ValueError("message required")

    # Fetch context
    triage_info = brief.generate_triage_brief(graph)
    eb_info = energy_balance.get_energy_balance(graph)
    goals = planner.list_goals(graph)

    active_goals_count = len([g for g in goals if g.get("attrs", {}).get("focus") is True])
    energy_level = eb_info.get("energy_level", 5.0)

    msg_lower = message.lower()
    if "triage" in msg_lower or "priority" in msg_lower or "today" in msg_lower:
        esc = triage_info.get("escalation")
        if esc:
            reply = f"Your top priority today is '{esc.get('title')}'. Reason: {esc.get('reason')}."
        else:
            reply = f"All clear! Your energy is at {energy_level}/10. You have {active_goals_count} active goals in focus."
    elif "energy" in msg_lower or "burnout" in msg_lower:
        reply = f"Energy status: {eb_info.get('burnout_risk').upper()} risk. Recommendation: {eb_info.get('recommendation')}"
    elif "goal" in msg_lower or "plan" in msg_lower:
        reply = f"You currently have {len(goals)} total goals ({active_goals_count} in focus). Keep your focus cap at 1 goal to maximize completion!"
    else:
        reply = f"I've reviewed your LifeOS graph: Energy level is {energy_level}/10 with {active_goals_count} active focus goals. How can I assist your week?"

    return {
        "reply": reply,
        "context_summary": {
            "energy_level": energy_level,
            "burnout_risk": eb_info.get("burnout_risk"),
            "active_goals": active_goals_count,
            "has_priority_escalation": triage_info.get("escalation") is not None,
        },
    }
