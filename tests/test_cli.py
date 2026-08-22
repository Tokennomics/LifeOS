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


def test_cli_export_command(graph: Graph, tmp_path):
    out_file = str(tmp_path / "test_export.zip")
    res = cli.main(["export", "--format", "Obsidian", "--output", out_file], graph=graph)
    assert res == 0
    import os, zipfile
    assert os.path.exists(out_file)
    with zipfile.ZipFile(out_file, "r") as z:
        assert "README.md" in z.namelist()


def test_cli_synthesize_command(graph: Graph):
    """Synthesising a day reads your rows; it writes nothing.

    This asserted that a `daily_reflection` memory was persisted, because the command was
    wired to a synthesiser that branched on the city name and sealed the result into the
    graph. Storing an invented day is worse than showing one — every screen that reads
    memories afterwards treats it as something you did.
    """
    res = cli.main(["synthesize"], graph=graph)
    assert res == 0
    session = graph.session("test", {"memories:read"})
    assert session.find_entities("memory", {"type": "daily_reflection"}, limit=5) == []
