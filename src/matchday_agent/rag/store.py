"""Async pgvector store for the RAG corpus (documents table).

- Singleton AsyncConnectionPool configured with register_vector_async so
  vector columns marshal transparently between Postgres and list[float].
- similar(query_vec, k, lang=None) for retrieval at query time.
- upsert_chunks(chunks) for idempotent bulk insertion during ingest.

DSN comes from DATABASE_URL (Supabase session pooler; see decisions § 0.4).
"""

from __future__ import annotations

import os
from typing import Any

from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool[Any] | None = None


async def _configure(conn: AsyncConnection[Any]) -> None:
    await register_vector_async(conn)


async def get_pool() -> AsyncConnectionPool[Any]:
    """Return the process-wide AsyncConnectionPool, opening it on first call."""
    global _pool
    if _pool is not None:
        return _pool
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set — required for pgvector store.")
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo=dsn,
        configure=_configure,
        min_size=1,
        max_size=5,
        open=False,
    )
    await pool.open()
    _pool = pool
    return pool


async def close_pool() -> None:
    """Close the singleton pool if open. Safe to call multiple times."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def similar(
    query_vec: list[float], k: int = 5, lang: str | None = None
) -> list[dict[str, Any]]:
    """Return top-k document chunks ordered by cosine distance to query_vec.

    Optionally filter by wiki_lang ('en', 'es'). Each returned dict includes
    a `distance` float (0 = identical, 2 = maximally opposite for cosine).
    """
    pool = await get_pool()
    vec = Vector(query_vec)
    if lang is not None:
        sql = """
            SELECT id, source_url, title, section_title, chunk_idx, content,
                   wiki_lang, embedding <=> %s AS distance
            FROM documents
            WHERE wiki_lang = %s
            ORDER BY embedding <=> %s
            LIMIT %s
        """
        params: tuple[Any, ...] = (vec, lang, vec, k)
    else:
        sql = """
            SELECT id, source_url, title, section_title, chunk_idx, content,
                   wiki_lang, embedding <=> %s AS distance
            FROM documents
            ORDER BY embedding <=> %s
            LIMIT %s
        """
        params = (vec, vec, k)
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()


async def upsert_chunks(chunks: list[dict[str, Any]]) -> int:
    """Bulk upsert chunks. Each dict must have keys matching the SQL below.

    ON CONFLICT (source_url, chunk_idx) DO UPDATE so re-runs of the
    ingestion script are idempotent (updates content, embedding, and
    updated_at). Returns the number of rows processed.
    """
    if not chunks:
        return 0
    pool = await get_pool()
    sql = """
        INSERT INTO documents
            (source_url, title, section_title, chunk_idx, content, embedding,
             wiki_lang, revision_id, updated_at)
        VALUES
            (%(source_url)s, %(title)s, %(section_title)s, %(chunk_idx)s,
             %(content)s, %(embedding)s, %(wiki_lang)s, %(revision_id)s, NOW())
        ON CONFLICT (source_url, chunk_idx) DO UPDATE SET
            content       = EXCLUDED.content,
            embedding     = EXCLUDED.embedding,
            title         = EXCLUDED.title,
            section_title = EXCLUDED.section_title,
            revision_id   = EXCLUDED.revision_id,
            updated_at    = NOW()
    """
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.executemany(sql, chunks)
    return len(chunks)


async def count_documents() -> int:
    """Utility: total row count of the documents table (for smoke checks)."""
    pool = await get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM documents")
        row = await cur.fetchone()
    return int(row[0]) if row else 0
