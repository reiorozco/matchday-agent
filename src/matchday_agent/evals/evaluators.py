"""Three evaluators for Phase 4 evals.

- correctness: Gemini LLM-as-judge, scores 1-5 vs reference_summary
- tool_selection: set overlap between actually-called tools (via
  run.child_runs) and expected_tools (via reference_outputs)
- latency_ms: wall-clock ms from run.start_time to run.end_time
"""

from __future__ import annotations

import json
from typing import Any

from langchain.chat_models import init_chat_model
from langsmith.schemas import Run

from matchday_agent.evals.judge_prompt import JUDGE_MODEL_ID, JUDGE_PROMPT_TEMPLATE

_KNOWN_TOOL_NAMES: set[str] = {
    "get_standings",
    "get_matches",
    "get_top_scorers",
    "find_team",
    "get_team_matches",
    "compare_teams",
    "search_football_context",
}


def _extract_called_tools(run: Run) -> set[str]:
    """Extract tool names called during a run via run.child_runs.

    Fallback: inspect the messages inside run.outputs if child_runs is
    empty (some LangGraph configurations don't expose child_runs at
    evaluator time).
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
    for msg in messages:
        name = getattr(msg, "name", None)
        if isinstance(name, str) and name in _KNOWN_TOOL_NAMES:
            called.add(name)
    return called


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
        content = response.content if isinstance(response.content, str) else str(response.content)
        parsed = _parse_judge_json(content)
        raw_score = parsed.get("score", 0)
        score = int(raw_score) if isinstance(raw_score, (int, float)) else 0
        score = max(1, min(5, score)) if score > 0 else 0
        return {
            "key": "correctness",
            "score": score,
            "comment": str(parsed.get("reasoning", ""))[:200],
        }
    except Exception as e:
        return {
            "key": "correctness",
            "score": 0,
            "comment": f"judge error: {type(e).__name__}: {e}",
        }


async def tool_selection_evaluator(
    outputs: dict[str, Any],
    reference_outputs: dict[str, Any],
    run: Run,
) -> dict[str, Any]:
    """Set overlap of actually-called tools vs expected_tools."""
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
