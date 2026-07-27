"""Runner for Phase 4 evals: `matchday_agent.evals.runner:main`.

Loads evals/anchor_cases.jsonl, compiles the same ReAct agent as
cli.py + app.py, invokes `langsmith.aevaluate()` with 3 evaluators
(correctness LLM-judge, tool_selection set-overlap, latency),
prints a Markdown table to stdout, writes evals/baseline.md.

Run:
    uv run --env-file .env evals
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langsmith import Client, aevaluate
from langsmith.utils import LangSmithNotFoundError

from matchday_agent.evals.dataset import load_examples
from matchday_agent.evals.evaluators import (
    correctness_evaluator,
    latency_evaluator,
    tool_selection_evaluator,
)
from matchday_agent.evals.judge_prompt import JUDGE_MODEL_ID
from matchday_agent.graph import build_agent
from matchday_agent.streaming import extract_chunk_text
from matchday_agent.tools.mcp_tools import MissingCredentialError, matchday_mcp_tools
from matchday_agent.tools.rag import search_football_context

DATASET_NAME = "matchday-agent-anchor-cases"
EXPERIMENT_PREFIX = "matchday-agent-phase4"
MAX_CONCURRENCY = 2
BASELINE_PATH = Path("evals/baseline.md")


def _ensure_dataset(
    client: Client, examples: list[dict[str, Any]], dataset_name: str
) -> str:
    """Read the dataset if it exists, else create it and upload examples.

    Uses a stable name so re-runs across days build on the same dataset
    in the LangSmith UI. If the JSONL content changes, delete the dataset
    from the UI first (or bump the name) to force a fresh upload.
    """
    try:
        existing = client.read_dataset(dataset_name=dataset_name)
        print(f"[dataset] reusing existing '{dataset_name}' (id={existing.id})")
        return dataset_name
    except LangSmithNotFoundError:
        print(f"[dataset] creating '{dataset_name}' with {len(examples)} examples")
        dataset = client.create_dataset(
            dataset_name=dataset_name,
            description="Phase 4 anchor cases (5 cases x 3 phrasing variations)",
        )
        client.create_examples(dataset_id=dataset.id, examples=cast(Any, examples))
        return dataset_name


def _resolve_model_id() -> str:
    provider = os.environ.get("LLM_PROVIDER", "groq")
    model = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
    return f"{provider}:{model}"


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int(len(sorted_values) * q)
    return sorted_values[min(idx, len(sorted_values) - 1)]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute-first, dict-second accessor for AsyncExperimentResults items."""
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


async def _collect_results(
    results: Any,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Iterate AsyncExperimentResults into per-row + aggregate stats."""
    rows: list[dict[str, Any]] = []
    correctness_scores: list[float] = []
    tool_scores: list[float] = []
    latency_scores: list[float] = []
    async for res in results:
        example = _get(res, "example")
        eval_wrapper = _get(res, "evaluation_results") or {}
        eval_results = _get(eval_wrapper, "results") or []
        metadata = getattr(example, "metadata", None) or {}
        row: dict[str, Any] = {
            "case_id": metadata.get("case_id", "?"),
            "case_name": metadata.get("case_name", "?"),
            "correctness": None,
            "tool_selection": None,
            "latency_ms": None,
        }
        for er in eval_results:
            key = _get(er, "key")
            score = _get(er, "score")
            if score is None:
                continue
            score_f = float(score)
            if key == "correctness":
                row["correctness"] = score_f
                correctness_scores.append(score_f)
            elif key == "tool_selection":
                row["tool_selection"] = score_f
                tool_scores.append(score_f)
            elif key == "latency_ms":
                row["latency_ms"] = score_f
                latency_scores.append(score_f)
        rows.append(row)
    aggregates = {
        "correctness_mean": sum(correctness_scores) / len(correctness_scores)
        if correctness_scores
        else 0.0,
        "tool_selection_mean": sum(tool_scores) / len(tool_scores) if tool_scores else 0.0,
        "latency_p50_ms": _percentile(latency_scores, 0.5),
        "latency_p95_ms": _percentile(latency_scores, 0.95),
    }
    return rows, aggregates


def _format_markdown_table(
    rows: list[dict[str, Any]],
    aggregates: dict[str, float],
    model_id: str,
) -> str:
    lines: list[str] = [
        "# matchday-agent evals baseline",
        "",
        f"- **Timestamp**: {datetime.now().isoformat(timespec='seconds')}",
        f"- **Model (agent)**: `{model_id}`",
        f"- **Model (judge)**: `{JUDGE_MODEL_ID}`",
        f"- **Experiment**: `{EXPERIMENT_PREFIX}`",
        f"- **Examples**: {len(rows)}",
        "",
        "## Aggregates",
        "",
        f"- correctness (mean, 1-5): **{aggregates['correctness_mean']:.2f}**",
        f"- tool_selection (mean, 0-1): **{aggregates['tool_selection_mean']:.2f}**",
        f"- latency p50 ms: **{aggregates['latency_p50_ms']:.0f}**",
        f"- latency p95 ms: **{aggregates['latency_p95_ms']:.0f}**",
        "",
        "## Per-case scores",
        "",
        "| case_id | case_name | correctness | tool_selection | latency_ms |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        c = f"{row['correctness']:.0f}" if row["correctness"] is not None else "-"
        t = f"{row['tool_selection']:.2f}" if row["tool_selection"] is not None else "-"
        lat = f"{row['latency_ms']:.0f}" if row["latency_ms"] is not None else "-"
        lines.append(f"| {row['case_id']} | {row['case_name']} | {c} | {t} | {lat} |")
    lines.extend(
        [
            "",
            "## Regression threshold (documented, not enforced in Phase 4)",
            "",
            "Per spec §4 exit: any future run whose correctness_mean drops by",
            "more than 0.5 vs this baseline should fail CI (Phase 6 addition).",
            "",
        ]
    )
    return "\n".join(lines)


async def _amain(limit: int | None = None) -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    if not os.environ.get("LANGSMITH_API_KEY"):
        print("LANGSMITH_API_KEY is not set", file=sys.stderr)
        return 2

    model_id = _resolve_model_id()
    print(f"[startup] agent-model={model_id} judge-model={JUDGE_MODEL_ID}")

    all_examples = load_examples()
    if limit is not None and limit > 0:
        examples = all_examples[:limit]
        dataset_name_target = f"{DATASET_NAME}-sample{limit}"
        print(
            f"[startup] --limit {limit}: using {len(examples)}/{len(all_examples)} examples "
            f"against separate dataset '{dataset_name_target}'"
        )
    else:
        examples = all_examples
        dataset_name_target = DATASET_NAME
        print(f"[startup] loaded {len(examples)} examples · dataset={dataset_name_target}")

    client = Client()
    dataset_name = _ensure_dataset(client, examples, dataset_name_target)

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
        agent = build_agent(model=model, tools=tools, checkpointer=checkpointer)
        print(f"[startup] agent built with {len(tools)} tools")

        async def target(inputs: dict[str, Any]) -> dict[str, Any]:
            thread_id = str(uuid.uuid4())
            config: RunnableConfig = {
                "configurable": {"thread_id": thread_id},
                "metadata": {
                    "eval_session_id": thread_id,
                    "model": model_id,
                    "env": "eval",
                },
                "tags": ["eval", "phase-4"],
            }
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=inputs["query"])]},
                config=config,
            )
            final_msg = result["messages"][-1]
            text = extract_chunk_text(final_msg)
            return {"output": text}

        print(f"\n[startup] running aevaluate (max_concurrency={MAX_CONCURRENCY})...\n", flush=True)
        results = await aevaluate(
            target,
            data=dataset_name,
            evaluators=cast(
                Any,
                [correctness_evaluator, tool_selection_evaluator, latency_evaluator],
            ),
            experiment_prefix=EXPERIMENT_PREFIX,
            description="Phase 4 baseline",
            metadata={"model": model_id, "judge": JUDGE_MODEL_ID, "env": "eval"},
            max_concurrency=MAX_CONCURRENCY,
            upload_results=True,
            client=client,
        )

        rows, aggregates = await _collect_results(results)
        table = _format_markdown_table(rows, aggregates, model_id)
        print(table)
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(table)
        print(f"\n[done] baseline written to {BASELINE_PATH}", flush=True)

    return 0


def _parse_limit_from_argv(argv: list[str]) -> int | None:
    """Parse `--limit N` or `--limit=N` from CLI args. Return None if absent."""
    for i, arg in enumerate(argv):
        if arg == "--limit" and i + 1 < len(argv):
            return int(argv[i + 1])
        if arg.startswith("--limit="):
            return int(arg.split("=", 1)[1])
    return None


def main() -> None:
    limit = _parse_limit_from_argv(sys.argv[1:])
    try:
        rc = asyncio.run(_amain(limit=limit))
    except KeyboardInterrupt:
        rc = 130
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
