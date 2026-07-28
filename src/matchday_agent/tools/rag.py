"""LangChain tool for RAG retrieval against the Wikipedia football corpus.

Bound into the agent in graph.py alongside the 6 MCP tools. The system
prompt (prompts/system.py) instructs the model to reach for this tool
on "rivalry / history / legendary" style questions.
"""

from __future__ import annotations

import asyncio
import os

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from matchday_agent.rag.embedder import embed_query
from matchday_agent.rag.store import similar

_MAX_K = 8
_CONTENT_PREVIEW_CHARS = 600
_TIMEOUT_SECONDS = 25.0

_RAG_DISABLED_MESSAGE = (
    "The Wikipedia knowledge base is temporarily unavailable while a smaller "
    "embedding model is being provisioned to fit the deploy VM memory. Answer "
    "without Wikipedia citations for now; the football-data.org MCP tools still "
    "cover current standings, fixtures, top scorers, and head-to-head data."
)


class SearchInput(BaseModel):
    query: str = Field(
        description=(
            "Natural-language query in Spanish or English about football history, "
            "rivalries, legendary players/matches, or cultural context. Do NOT use "
            "for current-season stats, standings, or fixtures — those come from the "
            "football-data.org MCP tools."
        )
    )
    k: int = Field(
        default=5,
        ge=1,
        le=_MAX_K,
        description=f"Number of Wikipedia chunks to return. Default 5. Max {_MAX_K}.",
    )


@tool("search_football_context", args_schema=SearchInput)
async def search_football_context(query: str, k: int = 5) -> str:
    """Search a Wikipedia-backed knowledge base for football history and context.

    Use for questions like: "historia del Clásico", "por qué es tan intensa la
    rivalidad Manchester United vs Liverpool", "finales legendarias del Real
    Madrid en la Champions", "contexto cultural del derbi de Madrid".

    Returns a citation-formatted list of up to `k` Wikipedia excerpts with
    their source URLs so the agent can cite them in its answer.

    Do NOT use for:
    - Current standings, fixtures, or top scorers (use get_standings,
      get_matches, get_top_scorers instead).
    - Real-time or in-season data (Wikipedia lags months behind).

    Wrapped in a 25 s timeout so the stream never hangs forever if the
    embedder or Supabase pgvector query stalls; on timeout returns a
    friendly notice the agent can gracefully fall back from (documented
    in decisions.md § 8 — post-spec-005 hotfix for Delta 3).

    Guarded by RAG_ENABLED env var: when set to "false", returns the
    disabled-notice message immediately WITHOUT loading the embedder
    (which would OOM the 512 MB Fly VM per audit finding — see
    decisions.md § 8.9). Default true; set false in fly.toml [env]
    while the model swap to multilingual-e5-small ships.
    """
    if os.environ.get("RAG_ENABLED", "true").lower() != "true":
        return _RAG_DISABLED_MESSAGE
    try:
        return await asyncio.wait_for(_search_impl(query, k), timeout=_TIMEOUT_SECONDS)
    except TimeoutError:
        return (
            f"RAG search timed out after {_TIMEOUT_SECONDS:.0f}s. "
            "The Wikipedia backend may be slow or unreachable. "
            "Try answering without RAG context if the question does not strictly need it."
        )


async def _search_impl(query: str, k: int) -> str:
    query_vec = await asyncio.to_thread(embed_query, query)
    hits = await similar(query_vec, k=k)
    if not hits:
        return "No relevant Wikipedia chunks found for this query."
    formatted: list[str] = []
    for i, h in enumerate(hits, 1):
        section = f" — {h['section_title']}" if h.get("section_title") else ""
        preview = h["content"]
        if len(preview) > _CONTENT_PREVIEW_CHARS:
            preview = preview[:_CONTENT_PREVIEW_CHARS] + "..."
        formatted.append(
            f"[{i}] {h['title']}{section} "
            f"(lang={h['wiki_lang']}, dist={h['distance']:.3f})\n"
            f"    URL: {h['source_url']}\n"
            f"    {preview}"
        )
    return "\n\n".join(formatted)
