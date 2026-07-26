"""Interactive REPL for the matchday-agent (Phase 1 verification surface).

Entry point declared in pyproject.toml [project.scripts]:
    mda = "matchday_agent.cli:main"

Run with:
    uv run --env-file .env mda [--session <uuid>] [--provider <p>] [--model <m>]

Behavior:
- One persistent MCP subprocess spawned at startup (Option B in decisions § 0.2).
- One AsyncPostgresSaver checkpointer scoped to the REPL lifetime.
- Streaming per turn via `astream_events(version="v2")` (same pattern the
  FastAPI SSE layer in Phase 3 will consume).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from contextlib import AsyncExitStack
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from matchday_agent.graph import build_agent
from matchday_agent.streaming import extract_chunk_text, format_tool_input
from matchday_agent.tools.mcp_tools import MissingCredentialError, matchday_mcp_tools
from matchday_agent.tools.rag import search_football_context

# ANSI dim/reset for tool-call annotations. Terminals without ANSI ignore.
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mda",
        description="Interactive REPL for the matchday football-analyst agent.",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Session UUID used as LangGraph thread_id. Default: fresh uuid4.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider (overrides $LLM_PROVIDER). E.g. groq, google_genai.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model (overrides $LLM_MODEL). E.g. llama-3.3-70b-versatile.",
    )
    return parser.parse_args(argv)


def _resolve_session_id(cli_value: str | None) -> str:
    if cli_value is None:
        return str(uuid.uuid4())
    try:
        uuid.UUID(cli_value)
    except ValueError as e:
        raise SystemExit(f"--session must be a valid UUID (got: {cli_value!r}): {e}") from e
    return cli_value


def _resolve_model_id(cli_provider: str | None, cli_model: str | None) -> str:
    provider = cli_provider or os.environ.get("LLM_PROVIDER", "groq")
    model = cli_model or os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    return f"{provider}:{model}"


async def _stream_turn(agent: Any, user_input: str, session_id: str) -> None:
    """Stream a single conversational turn to stdout using astream_events(v2)."""
    config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
    printed_any_token = False
    async for event in agent.astream_events(
        {"messages": [HumanMessage(content=user_input)]},
        config=config,
        version="v2",
    ):
        kind = event.get("event")
        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            text = extract_chunk_text(chunk)
            if text:
                print(text, end="", flush=True)
                printed_any_token = True
        elif kind == "on_tool_start":
            tool_name = event.get("name", "?")
            tool_input = event.get("data", {}).get("input", {})
            prefix = "\n" if printed_any_token else ""
            print(
                f"{prefix}{_DIM}[tool: {tool_name}({format_tool_input(tool_input)})]{_RESET}",
                flush=True,
            )
            printed_any_token = False
    print()


async def _repl(agent: Any, session_id: str) -> int:
    print(f"matchday-agent REPL — session {session_id}")
    print("Type your question in Spanish. Commands: /session, /exit, /quit. Ctrl-C to exit.\n")
    while True:
        try:
            raw = await asyncio.to_thread(input, "mda> ")
        except EOFError:
            print()
            return 0
        line = raw.strip()
        if not line:
            continue
        if line in {"/exit", "/quit"}:
            return 0
        if line == "/session":
            print(session_id)
            continue
        try:
            await _stream_turn(agent, line, session_id)
        except Exception as e:
            print(f"\n[error] {type(e).__name__}: {e}")


async def _amain(args: argparse.Namespace) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    session_id = _resolve_session_id(args.session)
    model_id = _resolve_model_id(args.provider, args.model)
    print(f"[startup] model={model_id} session={session_id}")

    model = init_chat_model(model_id, temperature=0.0)

    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(dsn))
        await checkpointer.setup()
        try:
            mcp_tools = await stack.enter_async_context(matchday_mcp_tools())
        except MissingCredentialError as e:
            print(f"[startup] {e}", file=sys.stderr)
            return 2
        tools = [*mcp_tools, search_football_context]
        print(f"[startup] loaded {len(tools)} tools: {', '.join(t.name for t in tools)}\n")
        agent = build_agent(model=model, tools=tools, checkpointer=checkpointer)
        return await _repl(agent, session_id)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    try:
        rc = asyncio.run(_amain(args))
    except KeyboardInterrupt:
        print("\n[exit]")
        rc = 130
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
