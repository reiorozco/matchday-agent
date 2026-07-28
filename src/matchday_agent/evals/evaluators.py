"""Three evaluators for Phase 4 evals.

- correctness: Gemini LLM-as-judge, scores 1-5 vs reference_summary
- tool_selection: set overlap between actually-called tools and expected_tools.
  Prefers the pre-extracted `called_tools` list in `outputs` (populated by
  the runner from `result["messages"]`) — child_runs / outputs.messages
  fallbacks are unreliable across provider shapes.
- latency_ms: wall-clock ms from run.start_time to run.end_time
"""

from __future__ import annotations

import json
from typing import Any

from langchain.chat_models import init_chat_model
from langsmith.schemas import Run

from matchday_agent.evals.judge_prompt import JUDGE_MODEL_ID, JUDGE_PROMPT_TEMPLATE
from matchday_agent.streaming import extract_chunk_text

_KNOWN_TOOL_NAMES: set[str] = {
    "get_standings",
    "get_matches",
    "get_top_scorers",
    "find_team",
    "get_team_matches",
    "compare_teams",
    "search_football_context",
}


def extract_called_tools_from_messages(messages: list[Any]) -> set[str]:
    """Extract tool names invoked from a list of LangChain messages.

    Handles both live BaseMessage objects (LangGraph result) and dicts
    (post-LangSmith-serialization). Used by both the runner's `target()`
    (to pre-extract for evaluator handoff) and the `tool_selection`
    evaluator's fallback.
    """
    called: set[str] = set()
    for msg in messages:
        name = msg.get("name") if isinstance(msg, dict) else getattr(msg, "name", None)
        if isinstance(name, str) and name in _KNOWN_TOOL_NAMES:
            called.add(name)
    return called


def _extract_called_tools(run: Run) -> set[str]:
    """Fallback: extract tool names from run.child_runs or run.outputs.

    Used only when the target's `called_tools` list is missing from
    outputs (defensive — LangSmith serialization can drop nested lists
    in edge cases).
    """
    called: set[str] = set()
    for child in run.child_runs or []:
        name = child.name
        if isinstance(name, str) and name in _KNOWN_TOOL_NAMES:
            called.add(name)
    if called:
        return called
    outputs = run.outputs or {}
    messages = outputs.get("messages") or []
    return extract_called_tools_from_messages(messages)


def _parse_judge_json(text: str) -> dict[str, Any]:
    """Parse the judge's JSON response, stripping common markdown fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    return json.loads(stripped)


async def correctness_evaluator(
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
) -> dict[str, Any]:
    """Gemini LLM-as-judge for correctness on a 1-5 scale."""
    judge = init_chat_model(JUDGE_MODEL_ID, temperature=0.0)
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        input=inputs.get("query", ""),
        reference_summary=reference_outputs.get("reference_summary", ""),
        output=outputs.get("output", ""),
    )
    try:
        response = await judge.ainvoke(prompt)
        content = extract_chunk_text(response)
        parsed = _parse_judge_json(content)
        raw_score = parsed.get("score", 0)
        score = int(raw_score) if isinstance(raw_score, (int, float)) else 0
        score = max(1, min(5, score)) if score > 0 else 0
        return {
            "key": "correctness_1_5",
            "score": score,
            "comment": str(parsed.get("reasoning", ""))[:200],
        }
    except Exception as e:
        return {
            "key": "correctness_1_5",
            "score": 0,
            "comment": f"judge error: {type(e).__name__}: {e}",
        }


async def tool_selection_evaluator(
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
    run: Run,
) -> dict[str, Any]:
    """Set overlap of actually-called tools vs expected_tools.

    Prefers `outputs["called_tools"]` populated by the runner (reliable
    across provider content shapes); falls back to `_extract_called_tools`
    on child_runs / outputs.messages only if the pre-extracted list is
    missing.
    """
    called_from_outputs = outputs.get("called_tools")
    if isinstance(called_from_outputs, list):
        called = {t for t in called_from_outputs if isinstance(t, str)}
    else:
        called = _extract_called_tools(run)
    expected_raw = reference_outputs.get("expected_tools") or []
    expected = set(expected_raw) if isinstance(expected_raw, list) else set()
    if not expected:
        return {"key": "tool_selection", "score": 1.0, "comment": "no expected tools"}
    overlap = len(called & expected)
    score = overlap / len(expected)
    return {
        "key": "tool_selection",
        "score": score,
        "comment": f"called={sorted(called)} expected={sorted(expected)}",
    }


async def latency_evaluator(run: Run) -> dict[str, Any]:
    """Wall-clock latency in ms from run.start_time to run.end_time."""
    if run.start_time and run.end_time:
        delta = run.end_time - run.start_time
        ms = delta.total_seconds() * 1000
        return {"key": "latency_ms", "score": float(ms)}
    return {"key": "latency_ms", "score": 0.0}
