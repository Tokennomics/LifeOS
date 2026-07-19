"""Apply the substrate schema (idempotent).

Usage: python -m substrate.migrate [--config path/to/config.yaml]
"""

import argparse

from substrate import ROOT, connect, load_config


def migrate(cfg: dict):
    """Apply the schema for the configured env; returns the open connection."""
    conn = connect(cfg)
    env = cfg.get("env", "sqlite")
    sql_file = ROOT / "substrate" / ("schema_sqlite.sql" if env == "sqlite" else "schema.sql")
    sql = sql_file.read_text(encoding="utf-8")
    if env == "sqlite":
        conn.executescript(sql)
    else:
        with conn.cursor() as cur:
            cur.execute(sql)
    conn.commit()
    return conn


def main():
    parser = argparse.ArgumentParser(description="Apply the Life OS substrate schema")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    conn = migrate(cfg)
    for table in ("entities", "edges", "observations", "grants"):
        cur = conn.execute(f"SELECT COUNT(*) AS n FROM {table}") if cfg.get("env", "sqlite") == "sqlite" else None
        if cur is None:
            with conn.cursor() as c:
                c.execute(f"SELECT COUNT(*) AS n FROM {table}")
                n = c.fetchone()["n"]
        else:
            n = cur.fetchone()[0]
        print(f"{table}: {n} rows")
    print(f"schema applied (env={cfg.get('env', 'sqlite')})")


if __name__ == "__main__":
    main()
