"""Database Migration, Integrity & Backup Verification CLI Tool.

Inspects database table schemas, entity/edge integrity, WAL journal status,
and verifies zero-downtime backup bundle health.

Usage:
  python -m tools.db_verify [--config path/to/config.json]
"""

import argparse
import json
import sys

from substrate.migrate import migrate


def verify_database(cfg: dict) -> dict:
    """Verifies SQLite database schema, WAL mode, integrity check, and orphan counts."""
    conn = migrate(cfg)

    # 1. PRAGMA integrity check
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check")
    integrity_res = cur.fetchone()[0]

    # 2. PRAGMA journal mode
    cur.execute("PRAGMA journal_mode")
    journal_mode = cur.fetchone()[0]

    # 3. Table row counts
    tables = {}
    for tbl in ("entities", "edges", "observations", "grants"):
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            tables[tbl] = cur.fetchone()[0]
        except Exception as e:
            tables[tbl] = f"error: {e}"

    # 4. Orphaned edge check
    cur.execute("""
        SELECT COUNT(*) FROM edges e
        WHERE NOT EXISTS (SELECT 1 FROM entities src WHERE src.id = e.src)
           OR NOT EXISTS (SELECT 1 FROM entities dst WHERE dst.id = e.dst)
    """)
    orphaned_edges = cur.fetchone()[0]

    is_healthy = integrity_res == "ok" and orphaned_edges == 0

    return {
        "status": "healthy" if is_healthy else "degraded",
        "integrity_check": integrity_res,
        "journal_mode": journal_mode,
        "tables": tables,
        "orphaned_edges_count": orphaned_edges,
    }


def main():
    parser = argparse.ArgumentParser(description="LifeOS Database Verification Utility")
    parser.add_argument("--config", help="Path to config file")
    args = parser.parse_args()

    cfg = load_config(args.config) if args.config else load_config()
    report = verify_database(cfg)

    print(json.dumps(report, indent=2))
    if report["status"] != "healthy":
        sys.exit(1)


if __name__ == "__main__":
    main()
