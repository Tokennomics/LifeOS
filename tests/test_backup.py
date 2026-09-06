"""Personal graph backup and restore.

Both tests here were rewritten after the fourth audit, because both encoded the behaviour
that turned out to be the vulnerability. `import_restore` used to return a bare `True` and
to accept an empty backup — and `test_gateway_backup_endpoints` asserted exactly that:
back up an empty graph, restore it, expect 200. That call is the instance wipe. It passed
for as long as the hole existed, which is why the suite never noticed.

The security properties themselves live in `tests/test_security_audit.py`; what is checked
here is that the feature still does its job.
"""

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from substrate import backup
from substrate.graph import Graph

PW = "correct-horse-battery"


def test_graph_backup_and_restore_operations(graph: Graph):
    session = graph.session("test", {"*"})
    session.create_entity("person", {"name": "Charlie"}, source="test")

    data = backup.export_backup(graph)
    assert len(data["entities"]) >= 1

    result = backup.import_restore(graph, data)
    assert result["restored"] is True
    assert result["entities"] == len(data["entities"])

    after = backup.export_backup(graph)
    assert any(entity["attrs"].get("name") == "Charlie" for entity in after["entities"])


def test_a_restore_brings_edges_back_with_it(graph: Graph):
    session = graph.session("test", {"*"})
    person = session.create_entity("person", {"name": "Rui"}, source="test")
    event = session.create_entity("event", {"title": "Climbing"}, source="test")
    session.create_edge(person, event, "attended", source="test")

    saved = backup.export_backup(graph)
    assert len(saved["edges"]) == 1

    backup.import_restore(graph, saved)
    restored = backup.export_backup(graph)
    assert len(restored["edges"]) == 1
    assert len(restored["entities"]) == 2


def test_restoring_an_empty_backup_is_refused(graph: Graph):
    """This is the wipe, and it is the whole finding: an empty body meant "delete
    everything, put nothing back", on an endpoint any signed-in user can call."""
    with pytest.raises(ValueError, match="at least one entity"):
        backup.import_restore(graph, {"entities": [], "edges": []})


def test_gateway_backup_endpoints(cfg):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/v1/people", headers=headers, json={"name": "Charlie"})

    exported = client.post("/v1/graph/backup", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["entities"], "a backup of a non-empty graph is not empty"

    restored = client.post("/v1/graph/restore", headers=headers, json=exported.json())
    assert restored.status_code == 200
    assert "Charlie" in repr(client.post("/v1/graph/backup", headers=headers).json())
