"""Assemble the ReAct football-analyst graph.

Thin wrapper over `create_react_agent` that injects our system prompt and
wires the given checkpointer. Kept intentionally minimal so we can swap
the underlying agent factory (e.g. `langchain.agents.create_agent`) in a
future phase without touching call sites.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from matchday_agent.prompts.system import SYSTEM_PROMPT


def build_agent(
    *,
    model: BaseChatModel,
    tools: list[BaseTool],
    checkpointer: BaseCheckpointSaver[Any],
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build the ReAct agent wired with SYSTEM_PROMPT and the given checkpointer."""
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        version="v2",
    )
