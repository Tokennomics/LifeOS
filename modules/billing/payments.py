"""Stripe & Payment Gateway Integration.

Subscription plan management (Free, Pro, Team), payment method processing,
and billing status tracking.
"""

from substrate.graph import Graph

SUPPORTED_PLANS = {"free", "pro", "team"}
SCOPES = {"people:read", "people:write"}
MODULE = "billing"


def create_customer(graph: Graph, account_id: str, email: str, source: str = MODULE) -> dict:
    """Creates or links a payment customer billing record."""
    session = graph.session(MODULE, SCOPES)
    person = session.get_entity(account_id)
    if not person or person.get("kind") != "person":
        raise ValueError(f"account '{account_id}' not found")

    attrs = person.get("attrs", {})
    customer_id = attrs.get("stripe_customer_id") or f"cus_mock_{account_id[:8]}"
    attrs["stripe_customer_id"] = customer_id
    attrs["email"] = email.lower().strip() if email else attrs.get("email", "")
    if "plan" not in attrs:
        attrs["plan"] = "free"
        attrs["subscription_status"] = "active"

    session.update_entity(account_id, attrs, source=source)
    return {
        "account_id": account_id,
        "stripe_customer_id": customer_id,
        "plan": attrs.get("plan", "free"),
    }


def subscribe_plan(graph: Graph, account_id: str, plan_id: str = "pro",
                   payment_token: str = "tok_mock", source: str = MODULE) -> dict:
    """Activates a subscription tier for an account."""
    plan_clean = plan_id.lower().strip()
    if plan_clean not in SUPPORTED_PLANS:
        raise ValueError(f"unsupported plan '{plan_id}' (supported: {sorted(list(SUPPORTED_PLANS))})")

    session = graph.session(MODULE, SCOPES)
    person = session.get_entity(account_id)
    if not person or person.get("kind") != "person":
        raise ValueError(f"account '{account_id}' not found")

    attrs = person.get("attrs", {})
    attrs["plan"] = plan_clean
    attrs["subscription_status"] = "active"
    session.update_entity(account_id, attrs, source=source)

    return {
        "account_id": account_id,
        "plan": plan_clean,
        "subscription_status": "active",
        "payment_processed": True,
    }


def get_billing_status(graph: Graph, account_id: str) -> dict:
    """Retrieves current subscription and billing status."""
    session = graph.session(MODULE, SCOPES)
    person = session.get_entity(account_id)
    if not person or person.get("kind") != "person":
        raise ValueError(f"account '{account_id}' not found")

    attrs = person.get("attrs", {})
    return {
        "account_id": account_id,
        "stripe_customer_id": attrs.get("stripe_customer_id", ""),
        "plan": attrs.get("plan", "free"),
        "subscription_status": attrs.get("subscription_status", "active"),
    }
