#!/usr/bin/env python3
"""
Phase 0.2 smoke test — spawn `npx matchday-mcp`, list tools, call get_standings.

Run:
    export FOOTBALL_DATA_TOKEN=...
    uv run python scripts/mcp_smoke.py

Expected: prints all 6 tool names + first 500 chars of the La Liga table.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "get_standings",
    "get_matches",
    "get_top_scorers",
    "find_team",
    "get_team_matches",
    "compare_teams",
}


async def main() -> int:
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    if not token:
        print("FOOTBALL_DATA_TOKEN is not set", file=sys.stderr)
        return 2

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "matchday-mcp"],
        # env merges with mcp.client.stdio.get_default_environment() (PATH, HOME…)
        env={"FOOTBALL_DATA_TOKEN": token},
    )

    async with (
        stdio_client(server_params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        tools_result = await session.list_tools()
        names = [t.name for t in tools_result.tools]
        print(f"tools ({len(names)}): {', '.join(names)}")

        missing = EXPECTED_TOOLS - set(names)
        if missing:
            print(f"MISSING tools: {missing}", file=sys.stderr)
            return 1

        call = await session.call_tool("get_standings", {"competition": "PD"})
        if not call.content:
            print("get_standings returned empty content", file=sys.stderr)
            return 1

        block = call.content[0]
        text = getattr(block, "text", str(block))
        print(f"\n--- get_standings(PD) ---\n{text[:500]}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
