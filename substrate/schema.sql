-- Life OS substrate schema — Postgres dialect (canonical).
-- FINAL for v0 (risk register #1): extend via attrs JSONB only.
-- Requires the pgvector extension for the embedding column.

CREATE EXTENSION IF NOT EXISTS vector;

-- entities: one table, typed
CREATE TABLE IF NOT EXISTS entities (
  id UUID PRIMARY KEY,
  kind TEXT NOT NULL,        -- person|interest|goal|task|event|place|memory|content|metric|decision|admin_item
  attrs JSONB NOT NULL DEFAULT '{}',
  embedding VECTOR(768),
  owner_id UUID NOT NULL,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
);

-- edges: typed, weighted, temporal
CREATE TABLE IF NOT EXISTS edges (
  id UUID PRIMARY KEY,
  src UUID,
  dst UUID,
  rel TEXT,                  -- attended|interested_in|blocks|located_at|with|feeds|decided
  weight REAL DEFAULT 1.0,
  attrs JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ
);

-- observations: provenance for EVERY write
CREATE TABLE IF NOT EXISTS observations (
  id UUID PRIMARY KEY,
  entity_id UUID,            -- entity OR edge id
  module TEXT,
  confidence REAL,
  source TEXT,
  created_at TIMESTAMPTZ
);

-- ACL for shared spaces (Hearth/crews) — unused in v0.1, present per schema
CREATE TABLE IF NOT EXISTS grants (
  subject UUID,
  scope TEXT,
  space UUID,
  granted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_entities_owner ON entities(owner_id);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_obs_entity ON observations(entity_id);
