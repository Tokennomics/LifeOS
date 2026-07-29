"""Phase 3b — Mutual-Consent Activity-Based Dating Engine.

Intent matching tied strictly to shared activities (e.g. climbing crew, sushi night).

CRITICAL PRIVACY INVARIANT:
Dating availability & interest are NEVER published to find_public, feed, or public crew rosters.
Interest is strictly invisible to non-matches and is ONLY revealed when mutual interest is verified
via two-way grant creation.
"""

from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "people:read"}
MODULE = "dating"


def express_interest(graph: Graph, target_account_id: str, activity_id: str,
                     account_id: str | None = None, source: str = MODULE) -> dict:
    """Expresses private activity-based interest in another account."""
    if not target_account_id.strip():
        raise ValueError("target_account_id required")
    if not activity_id.strip():
        raise ValueError("activity_id required")

    session = graph.session(MODULE, SCOPES)
    my_account = account_id or session.graph.default_owner or "self"

    # Store private dating intent (never public)
    existing = session.find_entities("content", {"type": "dating_intent", "user_id": my_account, "target": target_account_id, "activity": activity_id}, limit=1)
    if not existing:
        intent_id = session.create_entity(
            "content",
            {
                "type": "dating_intent",
                "user_id": my_account,
                "target": target_account_id,
                "activity": activity_id,
                "visibility": "private",  # Strictly private!
            },
            source=source,
        )
    else:
        intent_id = existing[0]["id"]

    # Check if target account has reciprocal interest in this activity
    target_intents = session.find_entities("content", {"type": "dating_intent", "user_id": target_account_id, "target": my_account, "activity": activity_id}, limit=1)

    is_mutual = len(target_intents) > 0
    if is_mutual:
        session.grant(target_account_id, "content:read", intent_id, source=source)
        session.grant(my_account, "content:read", target_intents[0]["id"], source=source)
        outcome = "mutual_match"
    else:
        outcome = "stored_privately"

    return {
        "intent_id": intent_id,
        "target_account_id": target_account_id,
        "activity_id": activity_id,
        "outcome": outcome,
        "is_mutual": is_mutual,
    }


def check_matches(graph: Graph, account_id: str | None = None) -> list[dict]:
    """Lists verified mutual matches for an account."""
    session = graph.session(MODULE, SCOPES)
    my_account = account_id or session.graph.default_owner or "self"
    my_intents = session.find_entities("content", {"type": "dating_intent", "user_id": my_account}, limit=200)

    matches = []
    for intent in my_intents:
        attrs = intent.get("attrs", {})
        target_id = attrs.get("target")
        activity_id = attrs.get("activity")
        if not target_id or not activity_id:
            continue

        target_intents = session.find_entities("content", {"type": "dating_intent", "user_id": target_id, "target": my_account, "activity": activity_id}, limit=1)

        if target_intents:
            matches.append({
                "match_id": intent["id"],
                "target_account_id": target_id,
                "activity_id": activity_id,
                "matched_at": intent.get("created_at", ""),
            })

    return matches
