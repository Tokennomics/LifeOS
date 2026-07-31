"""P2P Outing Debt Settler.

Updates splitting ledgers and marks debt balances as settled.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "ledger"


def settle_split(
    graph: Graph,
    split_id: str,
    settled_amount: float
) -> dict:
    """Settles an outstanding P2P split balance and logs transaction details."""
    if not split_id.strip():
        raise ValueError("split_id is required")
    if settled_amount <= 0:
        raise ValueError("settled_amount must be greater than zero")

    session = graph.session(MODULE, SCOPES)
    
    # Store settlement transaction
    attrs = {
        "type": "split_settlement",
        "split_id": split_id,
        "settled_amount": settled_amount,
        "status": "settled"
    }
    
    transaction_id = session.create_entity("metric", attrs, source="billing_settler")
    return {
        "transaction_id": transaction_id,
        "split_id": split_id,
        "settled_amount": settled_amount,
        "status": "success"
    }
