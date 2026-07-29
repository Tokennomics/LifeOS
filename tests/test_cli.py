import pytest
from substrate.graph import Graph
from tools import cli


def test_cli_capture_command(graph: Graph):
    res = cli.main(["capture", "Quick CLI test note"], graph=graph)
    assert res == 0

    session = graph.session("test", {"content:read"})
    captures = session.find_entities("content", {"type": "capture"}, limit=10)
    assert any(c.get("attrs", {}).get("text") == "Quick CLI test note" for c in captures)


def test_cli_plan_command(graph: Graph):
    res = cli.main(["plan"], graph=graph)
    assert res == 0


def test_cli_triage_command(graph: Graph):
    res = cli.main(["triage"], graph=graph)
    assert res == 0


def test_cli_steward_command(graph: Graph):
    res = cli.main(["steward"], graph=graph)
    assert res == 0
