"""FastAPI HTTP surface for matchday-agent.

Endpoints (see docs/api-contract.md for the frozen contract):
- GET  /            -> version + model + tool names
- GET  /health      -> Fly.io wake probe
- POST /chat        -> non-streaming JSON in/out (for evals + tests)
- POST /chat/stream -> SSE stream matching the frozen event shape

Lifespan composes the same AsyncExitStack as cli.py: AsyncPostgresSaver
(checkpointer) -> matchday_mcp_tools -> RAG tool -> compiled graph.
The compiled graph is shared across all requests; per-request state
(thread_id) is isolated by the checkpointer via the X-Session-Id header.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse
from starlette.status import HTTP_400_BAD_REQUEST

from matchday_agent import __version__
from matchday_agent.graph import build_agent
from matchday_agent.streaming import extract_chunk_text
from matchday_agent.tools.mcp_tools import MissingCredentialError, matchday_mcp_tools
from matchday_agent.tools.rag import search_football_context

_RATE_LIMIT = "20/minute"
_TOOL_RESULT_SUMMARY_CHARS = 300


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=4000,
        description="User question in Spanish. Max 4000 chars.",
    )


class ChatResponse(BaseModel):
    message: str
    session_id: str
    sources: list[str] = Field(default_factory=list)


def _validate_session_id(x_session_id: str | None) -> str:
    if not x_session_id:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="X-Session-Id header is required (UUID v4).",
        )
    try:
        uuid.UUID(x_session_id)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"X-Session-Id must be a valid UUID: {e}",
        ) from e
    return x_session_id


def _resolve_model_id() -> str:
    provider = os.environ.get("LLM_PROVIDER", "groq")
    model = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    return f"{provider}:{model}"


def _resolve_origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _summarize_tool_output(output: Any) -> str:
    if output is None:
        return ""
    content = getattr(output, "content", None)
    text = str(content) if content is not None else str(output)
    if len(text) > _TOOL_RESULT_SUMMARY_CHARS:
        return text[:_TOOL_RESULT_SUMMARY_CHARS] + "..."
    return text


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set — required for the checkpointer.")
    model_id = _resolve_model_id()
    model = init_chat_model(model_id, temperature=0.0)

    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(dsn))
        await checkpointer.setup()
        try:
            mcp_tools = await stack.enter_async_context(matchday_mcp_tools())
        except MissingCredentialError as e:
            raise RuntimeError(str(e)) from e
        tools = [*mcp_tools, search_football_context]
        agent = build_agent(model=model, tools=tools, checkpointer=checkpointer)

        app.state.agent = agent
        app.state.model_id = model_id
        app.state.tool_names = [t.name for t in tools]
        yield


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    lifespan=lifespan,
    title="matchday-agent",
    version=__version__,
    description="Football-analyst agent orchestrating MCP tools + Wikipedia RAG.",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, cast(Any, _rate_limit_exceeded_handler))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Session-Id"],
)


@app.get("/")
async def root(request: Request) -> dict[str, Any]:
    return {
        "name": "matchday-agent",
        "version": __version__,
        "model": request.app.state.model_id,
        "tools": request.app.state.tool_names,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@app.post("/chat", response_model=ChatResponse)
@limiter.limit(_RATE_LIMIT)
async def chat(
    request: Request,
    body: ChatRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> ChatResponse:
    session_id = _validate_session_id(x_session_id)
    agent = request.app.state.agent
    config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=body.message)]},
        config=config,
    )
    final_msg = result["messages"][-1]
    text = extract_chunk_text(final_msg)
    return ChatResponse(message=text, session_id=session_id, sources=[])


@app.post("/chat/stream")
@limiter.limit(_RATE_LIMIT)
async def chat_stream(
    request: Request,
    body: ChatRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> EventSourceResponse:
    session_id = _validate_session_id(x_session_id)
    agent = request.app.state.agent
    return EventSourceResponse(_sse_events(agent, body.message, session_id))


async def _sse_events(
    agent: Any, user_input: str, session_id: str
) -> AsyncIterator[dict[str, str]]:
    """Emit the frozen SSE event shape from LangGraph astream_events(v2)."""
    config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
    accumulated: list[str] = []
    try:
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
                    accumulated.append(text)
                    yield {"event": "token", "data": json.dumps({"text": text})}
            elif kind == "on_tool_start":
                tool_name = event.get("name", "?")
                tool_input = event.get("data", {}).get("input", {})
                run_id = str(event.get("run_id", ""))
                yield {
                    "event": "tool_call",
                    "data": json.dumps(
                        {
                            "tool": tool_name,
                            "input": tool_input
                            if isinstance(tool_input, dict)
                            else str(tool_input),
                            "id": run_id,
                        }
                    ),
                }
            elif kind == "on_tool_end":
                tool_name = event.get("name", "?")
                run_id = str(event.get("run_id", ""))
                summary = _summarize_tool_output(event.get("data", {}).get("output"))
                yield {
                    "event": "tool_result",
                    "data": json.dumps(
                        {
                            "id": run_id,
                            "tool": tool_name,
                            "ok": True,
                            "summary": summary,
                        }
                    ),
                }
        yield {
            "event": "final",
            "data": json.dumps({"message": "".join(accumulated), "sources": []}),
        }
    except Exception as e:
        yield {
            "event": "error",
            "data": json.dumps({"code": type(e).__name__, "message": str(e)}),
        }
