"""P2P Outing Payment Split Ledger.

Logs payment transactions and aggregates net debt balances across crew members.
"""

from collections import defaultdict
from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "ledger"


def record_payment(
    graph: Graph,
    payer_id: str,
    payee_id: str,
    amount: float,
    currency: str = "USD"
) -> str:
    """Records a single P2P payment transaction in the graph."""
    if not payer_id.strip() or not payee_id.strip():
        raise ValueError("payer_id and payee_id are required")
    if amount <= 0:
        raise ValueError("amount must be greater than zero")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "payment_transaction",
        "payer_id": payer_id,
        "payee_id": payee_id,
        "amount": amount,
        "currency": currency
    }
    
    return session.create_entity("admin_item", attrs, source="payments_ledger")


def calculate_balances(graph: Graph) -> dict:
    """Aggregates and compiles net balances across all recorded payments."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("admin_item", limit=1000)

    # Compile payer to payee balance changes
    net_balances = defaultdict(float)

    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "payment_transaction":
            payer = attrs.get("payer_id")
            payee = attrs.get("payee_id")
            amount = attrs.get("amount", 0.0)
            
            # Payer gives money to payee, so payee owes less or payer is owed
            net_balances[payer] += amount
            net_balances[payee] -= amount

    return {
        "net_balances": dict(net_balances)
    }
