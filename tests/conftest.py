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


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    """No test reaches the internet, whatever the host can reach.

    This is here because of a real failure rather than a principle. The sandbox these
    providers were written in cannot reach `api.open-meteo.com` or `overpass-api.de` — the
    network policy answers 403 — so a whole batch of tests asserted "conditions unavailable"
    and passed locally for the wrong reason. On CI, which has ordinary internet, Open-Meteo
    answered and six of them failed.

    A test whose result depends on whether the machine running it happens to have a route to
    a third party is not a test. Every provider's `_fetch` is replaced with a refusal, so a
    test that wants a response has to inject one — which the fixture-based tests already do
    by passing `fetch=`, and which is the only honest way to exercise parsing anyway.
    """
    from modules.feeds.providers import openmeteo, overpass, ticketmaster
    from modules.platform import webhooks

    def refuse(*args, **kwargs):
        raise OSError("outbound network is disabled in tests — inject a fetch instead")

    for provider in (openmeteo, overpass, ticketmaster):
        monkeypatch.setattr(provider, "_fetch", refuse)
    # Webhook delivery is outbound too. A test that wants a delivery passes `post=`, and a
    # test that wants a *failed* delivery now gets one deterministically rather than
    # depending on a hostname failing to resolve.
    monkeypatch.setattr(webhooks, "_post", refuse)


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
