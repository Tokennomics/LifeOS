import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.vault import semantic_notes
from substrate.graph import Graph


def test_vault_note_save_and_search(graph: Graph):
    note_res = semantic_notes.save_note(graph, "Atomic Habits Note", "Small 1% daily gains compound fast", tags=["habits", "productivity"])
    assert note_res["title"] == "Atomic Habits Note"
    assert "habits" in note_res["tags"]

    search_res = semantic_notes.search_vault(graph, query="compound")
    assert len(search_res) == 1
    assert search_res[0]["title"] == "Atomic Habits Note"

    tag_search = semantic_notes.search_vault(graph, tag="productivity")
    assert len(tag_search) == 1


def test_gateway_vault_endpoints(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "title": "Deep Work Takeaway",
        "content": "Work deeply for 90-minute blocks without distraction.",
        "tags": ["focus", "deep-work"],
    }
    resp_n = client.post("/v1/vault/notes", json=payload)
    assert resp_n.status_code == 200

    resp_s = client.get("/v1/vault/search?query=focus")
    assert resp_s.status_code == 200
    assert len(resp_s.json()) >= 1
