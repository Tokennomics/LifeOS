"""P2P Outing Resource Sharing Registry.

Coordinates resource registrations and loan requests within the crew.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "miniapp"


def register_resource(
    graph: Graph,
    owner_id: str,
    name: str
) -> dict:
    """Registers a shared physical resource node inside the graph."""
    if not owner_id.strip() or not name.strip():
        raise ValueError("owner_id and name are required")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "shared_resource",
        "owner_id": owner_id,
        "name": name,
        "status": "available"
    }
    
    resource_id = session.create_entity("content", attrs, source="resource_sharing")
    return {
        "resource_id": resource_id,
        "owner_id": owner_id,
        "name": name,
        "status": "available"
    }


def request_loan(
    graph: Graph,
    resource_id: str,
    borrower_id: str
) -> dict:
    """Requests a loan of a registered resource."""
    if not resource_id.strip() or not borrower_id.strip():
        raise ValueError("resource_id and borrower_id are required")

    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "resource_loan_request",
        "resource_id": resource_id,
        "borrower_id": borrower_id,
        "status": "pending"
    }
    
    request_id = session.create_entity("admin_item", attrs, source="resource_sharing")
    return {
        "request_id": request_id,
        "resource_id": resource_id,
        "borrower_id": borrower_id,
        "status": "pending"
    }
