-- Life OS substrate schema — SQLite dialect (dev fallback).
-- Mirrors schema.sql: UUIDs as TEXT, JSONB as TEXT (json), TIMESTAMPTZ as ISO-8601 TEXT,
-- embedding as BLOB (sqlite-vec integration deferred to Memento work).

CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  attrs TEXT NOT NULL DEFAULT '{}',
  embedding BLOB,
  owner_id TEXT NOT NULL,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS edges (
  id TEXT PRIMARY KEY,
  src TEXT,
  dst TEXT,
  rel TEXT,
  weight REAL DEFAULT 1.0,
  attrs TEXT NOT NULL DEFAULT '{}',
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY,
  entity_id TEXT,
  module TEXT,
  confidence REAL,
  source TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS grants (
  subject TEXT,
  scope TEXT,
  space TEXT,
  granted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_entities_owner ON entities(owner_id);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_obs_entity ON observations(entity_id);
