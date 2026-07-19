import pytest

from substrate.bus import Bus
from substrate.graph import Graph
from substrate.migrate import migrate

OWNER = "b0b00000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch):
    # Keep tests deterministic/offline regardless of what the host has configured.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


@pytest.fixture
def cfg(tmp_path):
    return {
        "env": "sqlite",
        "sqlite": {"path": str(tmp_path / "test.db")},
        "owner": {"id": OWNER, "name": "Bob"},
        "gateway": {"auth_token": ""},
        "telegram": {"token": "", "allowed_user_ids": []},
        "anthropic": {"api_key": ""},
    }


@pytest.fixture
def graph(cfg):
    conn = migrate(cfg)
    g = Graph(conn, Bus(), default_owner=OWNER)
    yield g
    conn.close()
