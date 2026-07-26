#!/usr/bin/env python3
"""Ingest Wikipedia football corpus into Supabase pgvector documents table.

Corpus (Phase 2 v1):
- 20 LaLiga 2024-25 clubs
- 20 Premier League 2024-25 clubs
- 10 famous matches / rivalries
- EN wiki pass on all 50; ES wiki pass on the 20 LaLiga clubs for
  cross-lingual retrieval quality.

Chunking: RecursiveCharacterTextSplitter.from_tiktoken_encoder (cl100k_base),
480 tokens per chunk + 64 token overlap. 480 (not 512) leaves headroom for
the E5 "passage: " prefix under the 512-token truncation limit.

Run:
    uv run --env-file .env python scripts/ingest_wikipedia.py

Re-runs are idempotent (UPSERT on source_url, chunk_idx).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

import wikipediaapi
from langchain_text_splitters import RecursiveCharacterTextSplitter

from matchday_agent.rag.embedder import embed_passages
from matchday_agent.rag.store import close_pool, count_documents, upsert_chunks

USER_AGENT = (
    "matchday-agent/0.1 (https://github.com/reiorozco/matchday-agent/issues) Wikipedia-API/0.15.0"
)

CHUNK_SIZE_TOKENS = 480
CHUNK_OVERLAP_TOKENS = 64
UPSERT_BATCH_SIZE = 100
EMBED_BATCH_SIZE = 100
MIN_CONTENT_CHARS = 100

LALIGA_CLUBS = [
    "Real Madrid CF",
    "FC Barcelona",
    "Atlético Madrid",
    "Athletic Bilbao",
    "Villarreal CF",
    "Real Betis",
    "Celta Vigo",
    "Rayo Vallecano",
    "CA Osasuna",
    "RCD Mallorca",
    "Real Sociedad",
    "Girona FC",
    "Getafe CF",
    "Valencia CF",
    "RCD Espanyol",
    "Sevilla FC",
    "Deportivo Alavés",
    "CD Leganés",
    "UD Las Palmas",
    "Real Valladolid",
]

PREMIER_LEAGUE_CLUBS = [
    "Arsenal F.C.",
    "Aston Villa F.C.",
    "AFC Bournemouth",
    "Brentford F.C.",
    "Brighton & Hove Albion F.C.",
    "Chelsea F.C.",
    "Crystal Palace F.C.",
    "Everton F.C.",
    "Fulham F.C.",
    "Ipswich Town F.C.",
    "Leicester City F.C.",
    "Liverpool F.C.",
    "Manchester City F.C.",
    "Manchester United F.C.",
    "Newcastle United F.C.",
    "Nottingham Forest F.C.",
    "Southampton F.C.",
    "Tottenham Hotspur F.C.",
    "West Ham United F.C.",
    "Wolverhampton Wanderers F.C.",
]

FAMOUS_MATCHES = [
    "El Clásico",
    "Madrid derby",
    "Old Firm",
    "Manchester derby",
    "Merseyside derby",
    "North London derby",
    "Derby della Madonnina",
    "Der Klassiker",
    "2024 UEFA Champions League final",
    "2025 UEFA Champions League final",
]


def _build_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=CHUNK_SIZE_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
    )


def _fetch_page(wiki: wikipediaapi.Wikipedia, title: str) -> dict[str, Any] | None:
    """Fetch a page synchronously. Returns dict or None for missing/stub pages."""
    page = wiki.page(title)
    if not page.exists():
        print(f"  MISSING: {title}")
        return None
    text = page.text
    if len(text.strip()) < MIN_CONTENT_CHARS:
        print(f"  STUB (<{MIN_CONTENT_CHARS} chars): {title}")
        return None
    return {
        "source_url": page.fullurl,
        "title": page.title,
        "revision_id": None,
        "text": text,
    }


async def _ingest_language_pass(titles: list[str], lang: str) -> int:
    """Fetch, chunk, embed, and upsert all pages for one wiki language.

    Returns the count of chunks upserted.
    """
    wiki = wikipediaapi.Wikipedia(user_agent=USER_AGENT, language=lang)
    splitter = _build_splitter()
    chunks: list[dict[str, Any]] = []

    print(f"\n=== Fetch {len(titles)} pages from {lang}.wikipedia.org ===")
    for title in titles:
        try:
            page_info = await asyncio.to_thread(_fetch_page, wiki, title)
        except Exception as e:
            print(f"  ERROR: {title}: {type(e).__name__}: {e}")
            continue
        if page_info is None:
            continue
        pieces = [p for p in splitter.split_text(page_info["text"]) if p.strip()]
        for idx, piece in enumerate(pieces):
            chunks.append(
                {
                    "source_url": page_info["source_url"],
                    "title": page_info["title"],
                    "section_title": None,
                    "chunk_idx": idx,
                    "content": piece,
                    "wiki_lang": lang,
                    "revision_id": page_info["revision_id"],
                }
            )
        print(f"  OK ({len(pieces)} chunks): {title}")

    if not chunks:
        print(f"  no chunks to embed for {lang}", flush=True)
        return 0

    print(
        f"\n=== Embed {len(chunks)} chunks (intfloat/multilingual-e5-large, 1024d) ===",
        flush=True,
    )
    texts = [c["content"] for c in chunks]
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch_texts = texts[i : i + EMBED_BATCH_SIZE]
        batch_embs = await asyncio.to_thread(embed_passages, batch_texts)
        embeddings.extend(batch_embs)
        print(f"  embedded {min(i + EMBED_BATCH_SIZE, len(texts))}/{len(texts)}", flush=True)
    for chunk, emb in zip(chunks, embeddings, strict=True):
        chunk["embedding"] = emb

    print(f"\n=== Upsert {len(chunks)} chunks (batch={UPSERT_BATCH_SIZE}) ===", flush=True)
    total = 0
    for i in range(0, len(chunks), UPSERT_BATCH_SIZE):
        batch = chunks[i : i + UPSERT_BATCH_SIZE]
        n = await upsert_chunks(batch)
        total += n
        print(f"  upserted {min(i + n, len(chunks))}/{len(chunks)}", flush=True)
    return total


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Wikipedia football corpus.")
    parser.add_argument(
        "--only-lang",
        choices=["en", "es"],
        default=None,
        help="If provided, ingest only this wiki language. Default: both en and es.",
    )
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    before = await count_documents()
    print(f"[before] documents rows: {before}", flush=True)

    en_count = 0
    es_count = 0

    if args.only_lang in (None, "en"):
        en_titles = LALIGA_CLUBS + PREMIER_LEAGUE_CLUBS + FAMOUS_MATCHES
        en_count = await _ingest_language_pass(en_titles, "en")

    if args.only_lang in (None, "es"):
        es_count = await _ingest_language_pass(LALIGA_CLUBS, "es")

    after = await count_documents()
    print("\n=== Summary ===", flush=True)
    print(f"  before rows:  {before}", flush=True)
    print(f"  EN chunks upserted: {en_count}", flush=True)
    print(f"  ES chunks upserted: {es_count}", flush=True)
    print(f"  after rows:   {after}", flush=True)
    print(f"  net delta:    {after - before}", flush=True)

    await close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
