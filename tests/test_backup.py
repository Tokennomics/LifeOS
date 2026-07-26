"""Backups — the part of hosting that only matters on the worst day of the year.

These tests exist because "it wrote a file" is not evidence of a backup. Each snapshot is
opened, integrity-checked and counted, which is exactly what the cron path does.
"""

import pathlib

import pytest

from substrate.bus import Bus
from substrate.graph import Graph
from substrate.migrate import migrate
from tools import backup


@pytest.fixture
def live(cfg):
    """A database with real rows in it, connection left open (as the gateway leaves it)."""
    conn = migrate(cfg)
    graph = Graph(conn, Bus(), default_owner=cfg["owner"]["id"])
    session = graph.session("seed", {"goals:write", "people:write"})
    for i in range(3):
        session.create_entity("goal", {"title": f"Goal {i}"}, source="seed")
    session.create_entity("person", {"name": "Ana"}, source="seed")
    yield cfg, conn
    conn.close()


def test_snapshot_captures_the_data_and_verifies_clean(live, tmp_path):
    cfg, _conn = live
    out = backup.snapshot(cfg, tmp_path)

    assert pathlib.Path(out["snapshot"]).exists() and out["bytes"] > 0
    counts = backup.verify(out["snapshot"])          # integrity_check + row counts
    assert counts["entities"] == 4
    assert counts["observations"] == 4               # provenance came along


def test_a_snapshot_taken_while_writes_continue_is_consistent(live, tmp_path):
    """The whole point of VACUUM INTO over a file copy: the source is live and in WAL mode,
    and the snapshot is still a complete, openable database."""
    cfg, conn = live
    graph = Graph(conn, Bus(), default_owner=cfg["owner"]["id"])
    session = graph.session("seed", {"goals:write"})

    out = backup.snapshot(cfg, tmp_path)
    session.create_entity("goal", {"title": "written after the snapshot"}, source="seed")

    counts = backup.verify(out["snapshot"])
    assert counts["entities"] == 4                   # the later write isn't in it, as expected
    assert backup.verify(backup.snapshot(cfg, tmp_path)["snapshot"])["entities"] == 5


def test_two_snapshots_in_the_same_second_both_survive(live, tmp_path):
    """VACUUM INTO refuses to overwrite. A backup must never be silently skipped because
    the clock hadn't ticked."""
    cfg, _conn = live
    first = backup.snapshot(cfg, tmp_path)
    second = backup.snapshot(cfg, tmp_path)
    assert first["snapshot"] != second["snapshot"]
    assert len(list(tmp_path.glob("lifeos-*.db"))) == 2


def test_retention_keeps_the_newest_and_prunes_the_rest(live, tmp_path):
    cfg, _conn = live
    for _ in range(5):
        backup.snapshot(cfg, tmp_path, keep=3)
    remaining = sorted(p.name for p in tmp_path.glob("lifeos-*.db"))
    assert len(remaining) == 3
    # what survived is the newest three (names sort chronologically)
    assert remaining == sorted(remaining)[-3:]


def test_pruning_only_ever_touches_files_it_wrote(live, tmp_path):
    """`--dest` may point at a shared directory. Retention must not be a delete-everything."""
    cfg, _conn = live
    bystander = tmp_path / "someone-elses-database.db"
    bystander.write_bytes(b"not ours")
    for _ in range(4):
        backup.snapshot(cfg, tmp_path, keep=1)
    assert bystander.exists() and bystander.read_bytes() == b"not ours"
    assert len(list(tmp_path.glob("lifeos-*.db"))) == 1


def test_keep_zero_prunes_nothing(live, tmp_path):
    """A misread flag should never be the thing that deletes every backup you have."""
    cfg, _conn = live
    backup.snapshot(cfg, tmp_path, keep=0)
    backup.snapshot(cfg, tmp_path, keep=0)
    assert len(list(tmp_path.glob("lifeos-*.db"))) == 2


def test_a_missing_database_is_a_loud_failure(cfg, tmp_path):
    cfg["sqlite"]["path"] = str(tmp_path / "nope.db")
    with pytest.raises(FileNotFoundError):
        backup.snapshot(cfg, tmp_path)


def test_postgres_is_refused_rather_than_half_supported(cfg, tmp_path):
    cfg["env"] = "postgres"
    with pytest.raises(ValueError, match="sqlite"):
        backup.snapshot(cfg, tmp_path)
