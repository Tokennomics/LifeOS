import json
import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.horizon import coach_reword


class MockClaudeGateway:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def prompt(self, system: str, user: str) -> str:
        return json.dumps([
            {"id": "p1", "body": "Empathetic reworded body text."}
        ])


def test_coach_reword_offline_fallback():
    proposals = [{"id": "p1", "title": "Test", "body": "Original text"}]
    # Without Claude
    res = coach_reword.reword_proposals(proposals, claude_gateway=None)
    assert res == proposals


def test_coach_reword_with_claude():
    proposals = [{"id": "p1", "title": "Test", "body": "Original text"}]
    mock_claude = MockClaudeGateway(enabled=True)
    res = coach_reword.reword_proposals(proposals, claude_gateway=mock_claude)
    assert res[0]["body"] == "Empathetic reworded body text."


def test_gateway_coach_reword_endpoint(cfg):
    app = create_app(cfg)
    client = TestClient(app)

    payload = {
        "proposals": [{"id": "p1", "title": "Test", "body": "Original body"}]
    }
    resp = client.post("/v1/coach/reword", json=payload)
    assert resp.status_code == 200
    assert resp.json()["proposals"][0]["body"] == "Original body"  # offline default in tests
