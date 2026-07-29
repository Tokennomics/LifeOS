import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.memento import journal
from substrate.graph import Graph


def test_journal_entry_logging(graph: Graph):
    entry_res = journal.log_journal_entry(graph, wins=["Shipped 3 modules"], gratitude=["Great focus window"], reflection="Steady compound gains", mood_rating=9)
    assert entry_res["mood_rating"] == 9

    entries = journal.get_journal_entries(graph)
    assert len(entries) >= 1
    assert any(e["mood_rating"] == 9 for e in entries)


def test_gateway_journal_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "wins": ["Completed test suite"],
        "gratitude": ["Good health and energy"],
        "reflection": "Consistent daily execution",
        "mood_rating": 8,
    }
    resp_c = client.post("/v1/journal/entries", json=payload)
    assert resp_c.status_code == 200

    resp_g = client.get("/v1/journal/entries")
    assert resp_g.status_code == 200
    assert len(resp_g.json()) >= 1
