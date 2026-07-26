"""Life OS substrate: shared context graph, event bus, config.

Law 1: every module READS from and WRITES to the shared context graph.
The Graph API (substrate.graph) is the ONLY write path.
"""

import datetime
import os
import pathlib
import uuid

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The scope the system itself owns: accounts, sessions — records that belong to no user's
# personal graph and must stay out of every owner-scoped view. It lives here rather than in
# the gateway so modules can resolve an account identity without importing a surface.
SYSTEM_OWNER = "00000000-0000-4000-8000-000000000000"


def load_config(path: str | None = None) -> dict:
    """Load config.yaml, resolving "env:NAME" values from the environment."""
    p = pathlib.Path(path) if path else pathlib.Path(os.environ.get("LIFEOS_CONFIG") or ROOT / "config.yaml")
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return _resolve_env(cfg)


def _resolve_env(node):
    if isinstance(node, dict):
        return {k: _resolve_env(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_env(v) for v in node]
    if isinstance(node, str) and node.startswith("env:"):
        return os.environ.get(node[4:], "")
    return node


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def connect(cfg: dict):
    """Open a DB connection for the configured env (sqlite | postgres)."""
    env = cfg.get("env", "sqlite")
    if env == "sqlite":
        import sqlite3

        path = cfg.get("sqlite", {}).get("path", "./data/lifeos.db")
        p = pathlib.Path(path)
        if not p.is_absolute():
            p = ROOT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI serves sync endpoints from a threadpool.
        # Safe for v0.1 (WAL mode, single user, short autocommitted transactions).
        conn = sqlite3.connect(str(p), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    if env == "postgres":
        import psycopg
        from psycopg.rows import dict_row

        dsn = cfg.get("postgres", {}).get("dsn", "")
        if not dsn:
            raise RuntimeError("postgres env selected but LIFEOS_PG_DSN is not set")
        return psycopg.connect(dsn, row_factory=dict_row)
    raise ValueError(f"unknown env: {env!r} (expected sqlite | postgres)")
