-- matchday-agent — Supabase schema (Phase 2).
-- Applied via Supabase MCP `apply_migration` (see docs/decisions.md § 2.x).
-- LangGraph's checkpointer creates its OWN tables via `AsyncPostgresSaver.setup()`;
-- do NOT touch those from here.

-- pgvector extension. Idempotent.
CREATE EXTENSION IF NOT EXISTS vector;

-- Documents table for RAG on Wikipedia chunks.
-- Vector dim = 1024 (intfloat/multilingual-e5-large; see decisions § 2.x).
CREATE TABLE IF NOT EXISTS documents (
    id             BIGSERIAL   PRIMARY KEY,
    source_url     TEXT        NOT NULL,
    title          TEXT        NOT NULL,
    section_title  TEXT,
    chunk_idx      INT         NOT NULL,
    content        TEXT        NOT NULL,
    embedding      vector(1024) NOT NULL,
    wiki_lang      VARCHAR(5)  NOT NULL,
    revision_id    BIGINT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_url, chunk_idx)
);

-- HNSW cosine similarity index — supported by pgvector >= 0.5.0.
-- Rebuild as IVFFlat only if we cross ~100k rows.
CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
  ON documents USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Ancillary index for language filtering.
CREATE INDEX IF NOT EXISTS idx_documents_wiki_lang
  ON documents (wiki_lang);
