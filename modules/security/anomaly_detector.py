"""Anomaly Detection & Threat Alert Engine.

Scans recent security and audit logs to identify potential threat indicators
such as brute-force authentication, rate limit breaches, and diagnostic integrity faults.
"""

from datetime import datetime, timezone
from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write"}
MODULE = "security"


def scan_security_anomalies(graph: Graph) -> list[dict]:
    """Scans system logs and security logs to compile active threat anomalies."""
    session = graph.session(MODULE, SCOPES)
    
    # Query system logs & security audit logs
    system_logs = session.find_entities("admin_item", {"type": "system_log"}, limit=200)
    audit_logs = session.find_entities("admin_item", {"type": "security_audit_log"}, limit=200)
    
    anomalies = []
    ip_failure_counts = {}

    # Analyze audit logs for repeated auth/scope errors
    for log in audit_logs:
        attrs = log.get("attrs", {})
        details = attrs.get("details", "")
        actor_id = attrs.get("actor_id", "unknown")
        event_type = attrs.get("event_type", "")

        # Look for repeated failed attempts or lockouts
        if "fail" in event_type.lower() or "unauthorized" in details.lower():
            anomalies.append({
                "source": "security_audit",
                "severity": "medium",
                "entity_id": log["id"],
                "message": f"Unauthorized security access event by actor '{actor_id}': {details}"
            })

    # Analyze system logs for performance/gateway rate limit issues
    for log in system_logs:
        attrs = log.get("attrs", {})
        level = attrs.get("level", "INFO").upper()
        message = attrs.get("message", "")
        metadata = attrs.get("metadata", {})

        if level == "ERROR":
            anomalies.append({
                "source": "system_log",
                "severity": "high",
                "entity_id": log["id"],
                "message": f"Critical system error in module '{attrs.get('module', 'unknown')}': {message}"
            })
        elif "rate limit" in message.lower() or "blocked" in message.lower():
            client_ip = metadata.get("client_ip", "unknown")
            ip_failure_counts[client_ip] = ip_failure_counts.get(client_ip, 0) + 1

    # Flag IP addresses triggering excessive rate limits
    for ip, count in ip_failure_counts.items():
        if count >= 3:
            anomalies.append({
                "source": "rate_limiter",
                "severity": "medium",
                "entity_id": ip,
                "message": f"IP address '{ip}' flagged for multiple rate-limiting block occurrences ({count} times)."
            })

    # Store any flagged anomalies in the DB for administrator review
    for anomaly in anomalies:
        session.create_entity(
            "admin_item",
            {
                "type": "security_anomaly_alert",
                "source": anomaly["source"],
                "severity": anomaly["severity"],
                "message": anomaly["message"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            source=MODULE
        )

    return anomalies
