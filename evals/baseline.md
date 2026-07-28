# matchday-agent evals baseline

- **Timestamp**: 2026-07-27T22:46:05
- **Model (agent)**: `google_genai:gemini-flash-latest`
- **Model (judge)**: `google_genai:gemini-flash-latest`
- **Experiment**: `matchday-agent-phase4`
- **Examples**: 15

## Aggregates

- correctness (mean, 1-5): **4.27**
- tool_selection (mean, 0-1): **0.92**
- latency p50 ms: **10154**
- latency p95 ms: **26893**

## Per-case scores

| case_id | case_name | correctness | tool_selection | latency_ms |
|---|---|---:|---:|---:|
| case3_v3 | compare_rm_barca | 5 | 0.67 | 15448 |
| case2_v3 | next_match_analysis | 1 | 1.00 | 16531 |
| case1_v1 | arriving_to_clasico | 5 | 0.75 | 10144 |
| case1_v2 | arriving_to_clasico | 5 | 1.00 | 16194 |
| case4_v3 | most_contested_league | 3 | 1.00 | 26893 |
| case5_v2 | laliga_weekend_summary | 5 | 1.00 | 22239 |
| case2_v1 | next_match_analysis | 5 | 1.00 | 8623 |
| case5_v3 | laliga_weekend_summary | 5 | 1.00 | 11024 |
| case3_v2 | compare_rm_barca | 4 | 0.67 | 9641 |
| case4_v2 | most_contested_league | 1 | 1.00 | 11452 |
| case3_v1 | compare_rm_barca | 5 | 1.00 | 7274 |
| case1_v3 | arriving_to_clasico | 5 | 0.75 | 10154 |
| case4_v1 | most_contested_league | 5 | 1.00 | 10150 |
| case5_v1 | laliga_weekend_summary | 5 | 1.00 | 6918 |
| case2_v2 | next_match_analysis | 5 | 1.00 | 7912 |

## Regression threshold (documented, not enforced in Phase 4)

Per spec §4 exit: any future run whose correctness_mean drops by
more than 0.5 vs this baseline should fail CI (Phase 6 addition).
