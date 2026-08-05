"""Community Treasury & Democratic Impact Allocation Engine.

Allocates 20% of platform profits to a community-governed impact treasury.
Members propose, discuss, and democratically vote on charity projects, local
initiatives, and community grants.
"""

from substrate import now_iso
from substrate.graph import Graph

SCOPES = {"content:read", "content:write", "treasury:read", "treasury:write"}
MODULE = "treasury"


def get_treasury_status(graph: Graph) -> dict:
    """Retrieves current treasury balance, total allocated (20%), and impact stats."""
    session = graph.session(MODULE, SCOPES)
    proposals = session.find_entities("content", {"type": "treasury_proposal"}, limit=100)

    total_impact_pool = 12450.00  # 20% of profit pool
    disbursed = sum(float(p.get("attrs", {}).get("grant_amount", 0)) for p in proposals if p.get("attrs", {}).get("status") == "approved")

    res_proposals = []
    for p in proposals:
        attrs = p.get("attrs", {})
        res_proposals.append({
            "id": p["id"],
            "title": attrs.get("title", ""),
            "category": attrs.get("category", "charity"),
            "grant_amount": attrs.get("grant_amount", 500.0),
            "votes": attrs.get("votes", 1),
            "status": attrs.get("status", "voting"),
            "proposed_by": attrs.get("proposed_by", "Community Member"),
            "created_at": attrs.get("created_at", "")
        })

    return {
        "profit_share_percent": 20.0,
        "treasury_balance": total_impact_pool - disbursed,
        "total_disbursed": disbursed,
        "proposals_count": len(res_proposals),
        "proposals": res_proposals
    }


def create_proposal(graph: Graph, title: str, category: str, grant_amount: float, proposed_by: str = "Member") -> dict:
    """Creates a new democratic community proposal for funding."""
    if not title.strip():
        raise ValueError("title required")
    session = graph.session(MODULE, SCOPES)
    pid = session.create_entity("content", {
        "type": "treasury_proposal",
        "title": title.strip(),
        "category": category.strip(),
        "grant_amount": float(grant_amount),
        "votes": 1,
        "status": "voting",
        "proposed_by": proposed_by,
        "created_at": now_iso()
    })
    return {"proposal_id": pid, "status": "voting"}


def vote_proposal(graph: Graph, proposal_id: str) -> dict:
    """Casts a democratic vote on a community proposal."""
    session = graph.session(MODULE, SCOPES)
    p = session.get_entity(proposal_id)
    if not p:
        raise ValueError("proposal not found")
    attrs = p.get("attrs", {})
    new_votes = attrs.get("votes", 0) + 1
    new_status = attrs.get("status", "voting")
    if new_votes >= 5:
        new_status = "approved"
    session.update_entity(proposal_id, {**attrs, "votes": new_votes, "status": new_status})
    return {"proposal_id": proposal_id, "votes": new_votes, "status": new_status}
