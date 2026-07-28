-- matchday-agent — Supabase schema (Phase 2, refreshed per § 8.10 audit response).
-- Reference DDL for reproduction on a fresh Supabase project. The live schema
-- was applied via psql direct against DATABASE_URL — Supabase MCP is in
-- read-only mode, so `apply_migration` was not usable (see decisions.md § 8.10).
-- LangGraph's checkpointer creates its OWN tables via `AsyncPostgresSaver.setup()`;
-- do NOT touch those from here.

-- pgvector extension. Idempotent.
CREATE EXTENSION IF NOT EXISTS vector;

-- Documents table for RAG on Wikipedia chunks.
-- Vector dim = 384 (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2;
-- see decisions.md § 8.10 for the swap from intfloat/multilingual-e5-large,
-- 2.24 GB, dim 1024 — that model OOM-killed the 512 MB Fly VM in prod).
CREATE TABLE IF NOT EXISTS documents (
    id             BIGSERIAL   PRIMARY KEY,
    source_url     TEXT        NOT NULL,
    title          TEXT        NOT NULL,
    section_title  TEXT,
    chunk_idx      INT         NOT NULL,
    content        TEXT        NOT NULL,
    embedding      vector(384) NOT NULL,
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
