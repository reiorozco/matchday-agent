-- matchday-agent — Supabase schema.
-- Applied manually via `psql "$DATABASE_URL" -f db/schema.sql` OR via Supabase MCP.
-- LangGraph's checkpointer creates its OWN tables via `AsyncPostgresSaver.setup()`;
-- do NOT touch those from here.

-- pgvector extension. Idempotent.
CREATE EXTENSION IF NOT EXISTS vector;

-- Documents table for RAG (Wikipedia chunks).
-- Dimension = 384 (paraphrase-multilingual-MiniLM-L12-v2 or BGE-small-en-v1.5).
-- Change to 1024 if we swap to Cohere embed-multilingual-v3 in Phase 2.
CREATE TABLE IF NOT EXISTS documents (
    id           BIGSERIAL PRIMARY KEY,
    source_url   TEXT NOT NULL,
    title        TEXT NOT NULL,
    chunk_idx    INT  NOT NULL,
    content      TEXT NOT NULL,
    embedding    vector(384) NOT NULL,
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_url, chunk_idx)
);

-- HNSW cosine similarity index — best for our scale (~2000 rows).
-- Rebuild as IVFFlat only if we cross ~100k rows.
CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
  ON documents USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Ancillary index for source-based filtering (e.g. "only clásico-tagged docs").
CREATE INDEX IF NOT EXISTS idx_documents_source_url
  ON documents (source_url);
