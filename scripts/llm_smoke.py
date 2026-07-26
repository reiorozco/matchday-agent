#!/usr/bin/env python3
"""Phase 0 LLM smoke — verify init_chat_model works with LLM_PROVIDER+LLM_MODEL env.

Run:
    uv run --env-file .env python scripts/llm_smoke.py

Swap providers by editing .env (e.g. LLM_PROVIDER=google_genai + LLM_MODEL=gemini-2.5-flash).
"""

from __future__ import annotations

import asyncio
import os
import sys

from langchain.chat_models import init_chat_model


async def main() -> int:
    provider = os.environ.get("LLM_PROVIDER", "groq")
    model = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    model_id = f"{provider}:{model}"

    print(f"model_id: {model_id}")

    llm = init_chat_model(model_id, temperature=0.0)

    prompt = "Responde solo con la palabra 'hola', en minúscula, sin puntuación."
    result = await llm.ainvoke(prompt)
    text = getattr(result, "content", str(result))
    print(f"response: {text!r}")

    if not hasattr(llm, "bind_tools"):
        print(f"FAIL: {model_id} does not support .bind_tools() — Phase 1 requires it", file=sys.stderr)
        return 1
    print("tool-calling: supported")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
