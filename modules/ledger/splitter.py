"""Multi-Currency Crew Expense Splitter.

Splits shared outing costs across multiple crew members.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "ledger"


def split_expenses(
    graph: Graph,
    total_amount: float,
    currency: str,
    payer_id: str,
    member_ids: list[str]
) -> dict:
    """Calculates split balances for shared outings."""
    if total_amount <= 0:
        raise ValueError("total_amount must be greater than zero")
    if not payer_id.strip():
        raise ValueError("payer_id required")
    if not member_ids:
        raise ValueError("member_ids list cannot be empty")

    all_participants = sorted(list(set([payer_id] + member_ids)))
    num_people = len(all_participants)
    share = total_amount / num_people

    splits = []
    for m in all_participants:
        if m == payer_id:
            continue
        splits.append({
            "from_member_id": m,
            "to_member_id": payer_id,
            "amount_owed": round(share, 2),
            "currency": currency
        })

    return {
        "total_amount": total_amount,
        "currency": currency,
        "payer_id": payer_id,
        "individual_share": round(share, 2),
        "splits": splits
    }
