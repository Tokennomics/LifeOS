"""Ledger Offline Sync Queue.

Buffers splits and expenses when Capacitor web clients reconnect.
"""

from substrate.graph import Graph

SCOPES = {"*"}
MODULE = "ledger"


def enqueue_sync_item(graph: Graph, split_data: dict) -> str:
    """Enqueues a pending split balance transaction."""
    session = graph.session(MODULE, SCOPES)
    attrs = {
        "type": "ledger_sync_item",
        "data": split_data
    }
    return session.create_entity("admin_item", attrs, source="ledger_sync")


def process_sync_queue(graph: Graph) -> list[dict]:
    """Processes and logs all buffered split transactions, clearing the queue."""
    session = graph.session(MODULE, SCOPES)
    items = session.find_entities("admin_item", limit=1000)
    
    synced = []
    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "ledger_sync_item":
            data = attrs.get("data", {})
            # Split expense processing logic
            from modules.ledger import splitter
            res = splitter.split_expenses(
                graph,
                total_amount=data.get("total_amount", 0.0),
                currency=data.get("currency", "USD"),
                payer_id=data.get("payer_id", ""),
                member_ids=data.get("member_ids", [])
            )
            synced.append(res)
            # Delete item from sync queue
            try:
                # We can execute a delete sql to remove the sync item
                conn = session.graph.conn
                conn.execute("DELETE FROM entities WHERE id = ?", (item["id"],))
                conn.commit()
            except Exception:
                pass

    return synced
