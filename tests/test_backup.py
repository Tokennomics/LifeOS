import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import backup
from substrate.graph import Graph


def test_graph_backup_and_restore_operations(graph: Graph):
    session = graph.session("test", {"*"})
    
    # Create simple node
    session.create_entity("person", {"name": "Charlie"}, source="test")
    
    data = backup.export_backup(graph)
    assert len(data["entities"]) >= 1

    # Restore backup
    ok = backup.import_restore(graph, data)
    assert ok is True

    # Re-verify Charlie exists
    data_after = backup.export_backup(graph)
    assert any(ent["attrs"].get("name") == "Charlie" for ent in data_after["entities"])


def test_gateway_backup_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    # Export backup
    resp_exp = client.post("/v1/graph/backup")
    assert resp_exp.status_code == 200
    
    # Restore backup
    backup_payload = resp_exp.json()
    resp_res = client.post("/v1/graph/restore", json=backup_payload)
    assert resp_res.status_code == 200
