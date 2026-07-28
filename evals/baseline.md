# matchday-agent evals baseline

- **Timestamp**: 2026-07-27T23:05:51
- **Model (agent)**: `google_genai:gemini-flash-latest`
- **Model (judge)**: `google_genai:gemini-flash-latest`
- **Experiment**: `matchday-agent-phase4`
- **Examples**: 15

## Aggregates

- correctness (mean, 1-5): **3.53**
- tool_selection (mean, 0-1): **0.88**
- latency p50 ms: **9053**
- latency p95 ms: **20752**

## Per-case scores

| case_id | case_name | correctness | tool_selection | latency_ms |
|---|---|---:|---:|---:|
| case4_v3 | most_contested_league | 5 | 1.00 | 10203 |
| case3_v2 | compare_rm_barca | 4 | 0.67 | 16492 |
| case5_v1 | laliga_weekend_summary | 1 | 1.00 | 8686 |
| case1_v1 | arriving_to_clasico | 5 | 0.75 | 7984 |
| case5_v2 | laliga_weekend_summary | 1 | 1.00 | 7825 |
| case2_v3 | next_match_analysis | 5 | 0.67 | 19509 |
| case3_v3 | compare_rm_barca | 3 | 0.67 | 10399 |
| case2_v2 | next_match_analysis | 5 | 1.00 | 8830 |
| case2_v1 | next_match_analysis | 5 | 1.00 | 20752 |
| case4_v2 | most_contested_league | 1 | 1.00 | 9993 |
| case4_v1 | most_contested_league | 4 | 1.00 | 9053 |
| case1_v2 | arriving_to_clasico | 5 | 0.75 | 10108 |
| case1_v3 | arriving_to_clasico | 0 | 1.00 | 8616 |
| case3_v1 | compare_rm_barca | 5 | 0.67 | 6282 |
| case5_v3 | laliga_weekend_summary | 4 | 1.00 | 8831 |

## Regression threshold (documented, not enforced in Phase 4)

Per spec §4 exit: any future run whose correctness_mean drops by
more than 0.5 vs this baseline should fail CI (Phase 6 addition).
