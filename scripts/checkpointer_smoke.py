#!/usr/bin/env python3
"""
Phase 0.4 smoke test — LangGraph state graph + AsyncPostgresSaver on Supabase.

Verifies:
1. `AsyncPostgresSaver.from_conn_string` connects.
2. `.setup()` is idempotent (safe on every boot).
3. State persists across script runs (checkpointer writes to Postgres).

Run:
    # Session pooler (port 5432) — the v1 pinned DSN. See docs/decisions.md §0.4.
    export DATABASE_URL='postgresql://postgres.vdggittczhvvszguqxez:<PASSWORD>@aws-0-ca-central-1.pooler.supabase.com:5432/postgres?sslmode=require'
    # First run:
    uv run python scripts/checkpointer_smoke.py
    # Second run — should see counter increase from prior run.
    uv run python scripts/checkpointer_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from typing import Annotated, TypedDict

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph


def _add(a: int, b: int) -> int:
    return a + b


class State(TypedDict):
    counter: Annotated[int, _add]  # reducer: incoming values ADD to prior state.


def bump(state: State) -> State:
    # This node contributes +1 which the reducer adds to the checkpointed value.
    return {"counter": 1}


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    # Stable thread id so repeated runs accumulate on the same state.
    thread_id = os.environ.get("THREAD_ID", "smoke-checkpointer")

    async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
        await checkpointer.setup()  # idempotent

        graph = StateGraph(State)
        graph.add_node("bump", bump)
        graph.add_edge(START, "bump")
        graph.add_edge("bump", END)
        app = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": thread_id}}

        # Peek at prior state (if any).
        prior = await app.aget_state(config)
        prior_counter = (prior.values or {}).get("counter", 0) if prior else 0
        print(f"prior counter for thread {thread_id!r}: {prior_counter}")

        # Invoke once; the reducer adds +1 on top of the checkpointed value.
        # First-ever run: 0 + 1 = 1. Second run: 1 + 1 = 2. And so on.
        result = await app.ainvoke({"counter": 0}, config=config)
        print(f"after invoke: counter = {result['counter']}")

        # Confirm persistence: re-read state fresh from Postgres.
        current = await app.aget_state(config)
        print(f"persisted state: {current.values}")
        print(f"checkpoint id: {getattr(current, 'config', {}).get('configurable', {}).get('checkpoint_id', 'n/a')}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
