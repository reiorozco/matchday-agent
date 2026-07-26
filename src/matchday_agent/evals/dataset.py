"""Loader for evals/anchor_cases.jsonl into raw dicts for LangSmith aevaluate().

The dataset is a local JSONL file (not a LangSmith-hosted dataset). For
purely-local eval runs we pass a list of plain dicts to `aevaluate(data=...)`
rather than `langsmith.schemas.Example` objects — the Example schema is
meant for hosted datasets and its default `dataset_id` (zero UUID) causes
LangSmith to attempt a 404-yielding server lookup.

The `expected_tools` list is put into `outputs` (not `metadata`) so the
tool_selection evaluator receives it via `reference_outputs` per the
LangSmith 0.10 evaluator signature convention.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATASET_PATH = Path("evals/anchor_cases.jsonl")


def load_examples(path: Path | None = None) -> list[dict[str, Any]]:
    """Load anchor cases from a JSONL file into raw dicts for aevaluate()."""
    dataset_path = path or DATASET_PATH
    examples: list[dict[str, Any]] = []
    with dataset_path.open() as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            examples.append(
                {
                    "inputs": {"query": row["input"]},
                    "outputs": {
                        "reference_summary": row["reference_summary"],
                        "expected_tools": row["expected_tools"],
                    },
                    "metadata": {
                        "case_id": row["id"],
                        "case_name": row["case_name"],
                    },
                }
            )
    return examples
