"""Shared streaming helpers between the CLI REPL and the FastAPI SSE emitter.

Extracted per docs/decisions.md § 1.5: do NOT diverge the REPL's event
handling from the SSE contract. Both surfaces normalize the same
provider-agnostic content shape and format tool inputs identically.
"""

from __future__ import annotations

from typing import Any


def extract_chunk_text(chunk: Any) -> str:
    """Normalize AIMessageChunk.content across providers.

    - Groq -> `str`
    - Gemini 3.x -> `list[dict]` where text parts carry a "text" key and
      reasoning parts do not.
    """
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def format_tool_input(tool_input: Any) -> str:
    """Render a tool_call input dict as `k=v, k=v` for compact logging."""
    if isinstance(tool_input, dict):
        return ", ".join(f"{k}={v!r}" for k, v in tool_input.items())
    return str(tool_input)
