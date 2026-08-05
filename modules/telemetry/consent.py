"""Opt-in Telemetry & Anonymized Recommendation Data Sharing Engine.

Allows users to explicitly opt-in to share anonymized interest tags, activity preferences,
and city event feedback to improve global recommendation quality (better events, crews,
friend matches, and mutual dates).

Privacy Guarantees:
1. Disabled by default (100% private).
2. User ID is hashed via SHA-256 (anonymized token).
3. Free text notes, private captures, and personal names are NEVER shared.
"""

import hashlib
from substrate import now_iso
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "interests:read"}
MODULE = "telemetry"


def set_consent(graph: Graph, enabled: bool = False, share_interests: bool = True,
                share_city_events: bool = True, source: str = MODULE) -> dict:
    """Updates telemetry & recommendation data sharing consent preferences."""
    session = graph.session(MODULE, SCOPES)
    existing = session.find_entities("content", {"type": "telemetry_consent"}, limit=1)

    payload = {
        "type": "telemetry_consent",
        "enabled": bool(enabled),
        "share_interests": bool(share_interests),
        "share_city_events": bool(share_city_events),
        "updated_at": now_iso()
    }

    if existing:
        consent_id = existing[0]["id"]
        session.update_entity(consent_id, payload, source=source)
    else:
        consent_id = session.create_entity("content", payload, source=source)

    return {"consent_id": consent_id, "enabled": enabled, "share_interests": share_interests, "share_city_events": share_city_events}


def get_consent(graph: Graph) -> dict:
    """Retrieves telemetry & recommendation data sharing consent preferences."""
    session = graph.session(MODULE, SCOPES)
    existing = session.find_entities("content", {"type": "telemetry_consent"}, limit=1)
    if not existing:
        return {"enabled": False, "share_interests": True, "share_city_events": True}
    attrs = existing[0].get("attrs", {})
    return {
        "enabled": bool(attrs.get("enabled", False)),
        "share_interests": bool(attrs.get("share_interests", True)),
        "share_city_events": bool(attrs.get("share_city_events", True)),
        "updated_at": attrs.get("updated_at", "")
    }


def anonymize_id(user_id: str) -> str:
    """Hashes user ID with SHA-256 for privacy-preserving federated recommendations."""
    return hashlib.sha256(str(user_id or "anon").encode("utf-8")).hexdigest()[:16]
