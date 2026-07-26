"""MCP client: spawn `npx matchday-mcp` and expose its 6 tools as LangChain BaseTools.

Pattern from docs/decisions.md § 0.2 (Option B — persistent session for the
process lifetime, spawned once at startup and reused for every request).
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client


class MissingCredentialError(RuntimeError):
    """Raised when a required credential is missing from the environment."""


@asynccontextmanager
async def matchday_mcp_tools() -> AsyncGenerator[list[BaseTool]]:
    """Spawn `npx -y matchday-mcp` over stdio and yield its tools as BaseTools.

    Reads FOOTBALL_DATA_TOKEN from the environment and forwards it to the
    subprocess. The stdio subprocess and the MCP `ClientSession` are closed
    when the context exits.
    """
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    if not token:
        raise MissingCredentialError("FOOTBALL_DATA_TOKEN is required to spawn matchday-mcp.")

    # Merge our subprocess env on top of the parent's PATH/HOME/etc,
    # per mcp.client.stdio.get_default_environment().
    subprocess_env = get_default_environment()
    subprocess_env["FOOTBALL_DATA_TOKEN"] = token

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "matchday-mcp"],
        env=subprocess_env,
    )

    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = await load_mcp_tools(session)
        yield tools
