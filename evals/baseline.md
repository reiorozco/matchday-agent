# matchday-agent evals baseline

## STATUS: PLACEHOLDER — infrastructure verified, quantitative baseline pending quota reset

**Captured**: 2026-07-26T14:02:32

**Infrastructure verified**: dataset `matchday-agent-anchor-cases` created in
LangSmith, 15 examples uploaded, `aevaluate()` ran all 15 cases with
`error_handling='log'`, all 3 evaluators registered, `baseline.md` written by
the runner, `.env` provider swap validated (Groq -> Gemini -> back).

**Quantitative scores blocked by free-tier daily quotas**. Both attempted
providers hit their per-day limits during evaluation:

- **Groq** `llama-3.3-70b-versatile`: TPD 97,286 / 100,000 tokens used across
  Phases 1-4 combined. Every call returned HTTP 429 (`rate_limit_exceeded`,
  ~5 min retry-after but rolling 24h window means daily exhaustion). 15/15
  agent invocations failed.
- **Gemini** `gemini-3.5-flash`: Google's free-tier day quota is 20
  requests / model / project
  (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). 15 agent + judge
  calls exceeded 20 quickly. 15/15 agent invocations failed with HTTP 429
  (`RESOURCE_EXHAUSTED`).

**How to regenerate a real baseline**:

1. Wait for the daily quotas to reset (~24 h from 2026-07-26).
2. `uv run --env-file .env evals` (with `.env` at defaults — Groq primary).
3. This file will be overwritten with actual scores.
4. If Groq daily budget is still tight in prod, either (a) upgrade to Groq's
   Dev Tier, or (b) flip `LLM_PROVIDER=google_genai` in `.env` and rerun
   (Gemini free-tier is 20/day/model — enough for 1 clean eval per day).

## Aggregates (quota-blocked run — DO NOT interpret as baseline)

- correctness (mean, 1-5): **0.00** (blocked)
- tool_selection (mean, 0-1): **0.00** (blocked)
- latency p50 ms: **36392** (mostly Google API retry backoff time)
- latency p95 ms: **56311** (mostly Google API retry backoff time)

## Per-case scores (all quota-blocked)

| case_id | case_name | correctness | tool_selection | latency_ms |
|---|---|---:|---:|---:|
| case1_v1 | arriving_to_clasico | 0 | 0.00 | 36562 |
| case1_v2 | arriving_to_clasico | 0 | 0.00 | 34821 |
| case1_v3 | arriving_to_clasico | 0 | 0.00 | 37009 |
| case2_v1 | next_match_analysis | 0 | 0.00 | 36835 |
| case2_v2 | next_match_analysis | 0 | 0.00 | 36087 |
| case2_v3 | next_match_analysis | 0 | 0.00 | 56311 |
| case3_v1 | compare_rm_barca | 0 | 0.00 | 36392 |
| case3_v2 | compare_rm_barca | 0 | 0.00 | 36529 |
| case3_v3 | compare_rm_barca | 0 | 0.00 | 47396 |
| case4_v1 | most_contested_league | 0 | 0.00 | 34577 |
| case4_v2 | most_contested_league | 0 | 0.00 | 35431 |
| case4_v3 | most_contested_league | 0 | 0.00 | 36094 |
| case5_v1 | laliga_weekend_summary | 0 | 0.00 | 36947 |
| case5_v2 | laliga_weekend_summary | 0 | 0.00 | 35850 |
| case5_v3 | laliga_weekend_summary | 0 | 0.00 | 35636 |

## Regression threshold (documented, not enforced in Phase 4)

Per spec § 4 exit: any future run whose correctness_mean drops by more than
0.5 vs this baseline should fail CI (Phase 6 addition). Cannot be applied
until a real (non-quota-blocked) baseline is captured.

## Meta

- **Experiment**: `matchday-agent-phase4` (visible in the LangSmith UI —
  all 15 traces uploaded even though they errored, useful for tag /
  metadata inspection).
- **Model (agent, attempted)**: `groq:llama-3.3-70b-versatile` first, then
  `google_genai:gemini-3.5-flash` after Groq TPD hit.
- **Model (judge)**: `google_genai:gemini-3.5-flash` (never invoked because
  the agent errored out first in every case).
- **Dataset in LangSmith**: `matchday-agent-anchor-cases` — 15 examples,
  reused across reruns via `read_dataset` + fallback-to-`create_dataset`.
