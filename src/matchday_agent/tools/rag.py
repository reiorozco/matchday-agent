"""LangChain tool for RAG retrieval against the Wikipedia football corpus.

Bound into the agent in graph.py alongside the 6 MCP tools. The system
prompt (prompts/system.py) instructs the model to reach for this tool
on "rivalry / history / legendary" style questions.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from matchday_agent.rag.embedder import embed_query
from matchday_agent.rag.store import similar

_MAX_K = 8
_CONTENT_PREVIEW_CHARS = 600


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
    their source URLs so the agent can cite them in the Spanish answer.

    Do NOT use for:
    - Current standings, fixtures, or top scorers (use get_standings,
      get_matches, get_top_scorers instead).
    - Real-time or in-season data (Wikipedia lags months behind).
    """
    query_vec = await asyncio.to_thread(embed_query, query)
    hits = await similar(query_vec, k=k)
    if not hits:
        return "No se encontraron chunks relevantes en la base de Wikipedia."
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
