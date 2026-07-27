"""Back up the Life OS database — consistently, on a schedule.

**Copying the database file is not a backup.** With WAL enabled (which `substrate.connect`
turns on) the live file is only half the story: recent commits sit in `-wal` until a
checkpoint, and a copy taken mid-transaction can restore as a corrupt database. It will
usually look fine, which is the dangerous part — you find out at restore time.

`VACUUM INTO` asks SQLite itself for the snapshot. It takes a read lock, writes a complete,
already-compacted database to a new path, and never blocks readers. That is the supported
way to back up a live SQLite database, so it is the only way this tool does it.

Usage (cron on the VPS):
    python -m tools.backup --keep 14 --dest /var/backups/lifeos

Restoring is a file copy back into place with the gateway stopped — a snapshot is a plain
database, not an archive format, so there is nothing to un-pack and nothing to go wrong.
"""

import argparse
import datetime
import pathlib

from substrate import ROOT, load_config

PREFIX = "lifeos-"
SUFFIX = ".db"


def _db_path(cfg: dict) -> pathlib.Path:
    if cfg.get("env", "sqlite") != "sqlite":
        raise ValueError("backup only supports the sqlite env (postgres has its own tooling)")
    path = pathlib.Path(cfg.get("sqlite", {}).get("path", "./data/lifeos.db"))
    return path if path.is_absolute() else ROOT / path


def _stamp(now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def snapshot(cfg: dict, dest_dir: str | pathlib.Path | None = None, keep: int = 14) -> dict:
    """Write a consistent snapshot and prune old ones. Returns what it did.

    `keep` is a floor on history, not a cap on disk: pruning only ever removes files this
    tool wrote (matched by name), so pointing `--dest` at a shared directory can't delete
    somebody else's data.
    """
    import sqlite3

    src = _db_path(cfg)
    if not src.exists():
        raise FileNotFoundError(f"no database at {src}")
    dest_dir = pathlib.Path(dest_dir) if dest_dir else src.parent / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # VACUUM INTO refuses to overwrite, so a second run inside the same second needs a
    # distinct name rather than a failure — backups must never be skipped silently.
    base = _stamp()
    out = dest_dir / f"{PREFIX}{base}{SUFFIX}"
    n = 1
    while out.exists():
        out = dest_dir / f"{PREFIX}{base}-{n}{SUFFIX}"
        n += 1

    conn = sqlite3.connect(str(src))
    try:
        conn.execute("VACUUM INTO ?", (str(out),))
    finally:
        conn.close()

    size = out.stat().st_size
    pruned = _prune(dest_dir, keep, protect=out)
    return {"source": str(src), "snapshot": str(out), "bytes": size,
            "pruned": [str(p) for p in pruned], "kept": keep}


def _prune(dest_dir: pathlib.Path, keep: int, protect: pathlib.Path | None = None) -> list:
    """Delete all but the newest `keep` snapshots.

    Ordered by mtime, not by filename: the collision suffix (`...Z-1.db`) sorts *before*
    the plain name because '-' < '.', so a name sort would have made the newest snapshot
    of a busy second look like the oldest and delete it. `protect` is a second belt — the
    snapshot just taken is never a pruning candidate, whatever the ordering says.
    """
    if keep <= 0:
        return []
    candidates = [p for p in dest_dir.glob(f"{PREFIX}*{SUFFIX}") if p != protect]
    candidates.sort(key=lambda p: (p.stat().st_mtime, p.name))
    doomed = candidates[:-(keep - 1)] if keep > 1 else candidates
    for path in doomed:
        path.unlink()
    return doomed


def verify(path: str | pathlib.Path) -> dict:
    """Open a snapshot and count what's in it.

    A backup nobody has ever opened is a hope, not a backup — so the cron path verifies
    every snapshot it takes, and a failure here is a failure of the whole run.
    """
    import sqlite3

    conn = sqlite3.connect(str(path))
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(f"integrity check failed for {path}")
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("entities", "edges", "observations", "grants")}
    finally:
        conn.close()
    return counts


def main():
    parser = argparse.ArgumentParser(description="Snapshot the Life OS database")
    parser.add_argument("--config", default=None)
    parser.add_argument("--dest", default=None, help="backup directory (default: <data>/backups)")
    parser.add_argument("--keep", type=int, default=14, help="how many snapshots to retain")
    args = parser.parse_args()

    result = snapshot(load_config(args.config), args.dest, args.keep)
    counts = verify(result["snapshot"])
    print(f"{result['snapshot']}  {result['bytes']} bytes  "
          + " ".join(f"{k}={v}" for k, v in counts.items()))
    for path in result["pruned"]:
        print(f"pruned {path}")


if __name__ == "__main__":
    main()
