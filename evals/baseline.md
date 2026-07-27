# matchday-agent evals baseline

## STATUS: infrastructure verified · quantitative baseline pending free-tier quota reset

**Last attempt**: 2026-07-27T15:56:19 (local)
**Attempts today**: 3 (all quota-blocked, see attempt log below)
**Full context**: [docs/decisions.md § 4.6–4.9](../docs/decisions.md)

Prior status: [Phase 4 § 4.3](../docs/decisions.md) documented Groq TPD
+ Gemini 20-req/day free-tier caps. This file is the runtime placeholder
until either quota resets under sustained conditions OR one provider is
upgraded to a paid tier.

## Infrastructure verified

- Dataset `matchday-agent-anchor-cases` (15 examples) + subset
  `matchday-agent-anchor-cases-sample5` (5 examples via `--limit 5`) both
  hosted in LangSmith.
- Runner `uv run --env-file .env evals [--limit N]` — the `--limit N`
  flag was closed today (Phase 4 § 4.7 in decisions.md).
- Judge model swapped to `google_genai:gemini-flash-latest` (Phase 4
  § 4.6) — the pinned `gemini-3.5-flash` is currently on Google-side
  HTTP 503 UNAVAILABLE.
- All 3 evaluators (correctness / tool_selection / latency) registered
  and invoked cleanly. `aevaluate(error_handling='log')` captures
  per-example errors without aborting the run.
- `baseline.md` policy locked in Phase 4 § 4.9: never commit
  runner-generated 0-score tables as if they were real baselines.

## Attempt log (2026-07-27)

| # | Config                                                                          | Wall-clock | Result                                                                                                        |
|---|---------------------------------------------------------------------------------|-----------:|---------------------------------------------------------------------------------------------------------------|
| 1 | agent=`groq:llama-3.3-70b-versatile`, judge=`gemini-flash-latest`, 15 cases     | 6 m 27 s   | 10× RateLimitError (Groq TPD) + 6× tool_use_failed (Groq near-cap degradation § 3.6). All 15 → 0 score.       |
| 2 | agent=`groq:llama-3.3-70b-versatile`, judge=`gemini-flash-latest`, `--limit 5`  | 1 m 20 s   | All 5 → tool_use_failed. Groq degradation continues even at ~10 k-token load.                                  |
| 3 | agent=`gemini-flash-latest`, judge=`gemini-flash-latest`, `--limit 5`           | 2 m 56 s   | Gemini RESOURCE_EXHAUSTED — 20-req/day cap for `gemini-3.6-flash` (alias resolution) exhausted within the run. |

Prior attempt log (2026-07-26): see the pre-2026-07-27 state of this
file in the git history — same STATUS shape, same root cause.

## Infra latency observations (real signal even when scores are 0)

From attempt 2 (agent=Groq degraded, `--limit 5`):

- p50: 13 094 ms · p95: 23 405 ms — variance is retry-and-backoff noise.

From attempt 3 (agent=Gemini quota-exhausted, `--limit 5`):

- p50: 39 808 ms · p95: 58 867 ms — Gemini SDK's tenacity retry is more
  aggressive than Groq's, pushing wall-clock much higher for the same
  outcome.

These latencies do NOT reflect happy-path agent latency. Once a real
baseline is captured, expect p50 ≈ 3-5 s (single-tool Groq case) and
p95 ≈ 15-25 s (parallel-tool case #4 with 5 concurrent MCP fetches).

## Regeneration recipe

When quotas allow (either wait 24+ h under NO load, or upgrade one
provider to paid tier):

1. **Fast sanity** — probe both providers first:
   ```bash
   uv run --env-file .env python scripts/llm_smoke.py
   LLM_PROVIDER=google_genai LLM_MODEL=gemini-flash-latest \
     uv run --env-file .env python scripts/llm_smoke.py
   ```
2. **Sampled baseline** — cheaper, real signal on 5 anchor cases:
   ```bash
   uv run --env-file .env evals --limit 5
   ```
3. **Full baseline** — 15 examples, needs quota headroom:
   ```bash
   uv run --env-file .env evals
   ```
4. On success, the runner overwrites this file with real scores;
   commit as-is. On failure, restore this placeholder shape per
   Phase 4 § 4.9 policy.

**Escape hatches** if free tier stays blocked:

- **Groq Dev Tier**: eliminates the 100 k TPD cap on the agent side.
- **Fresh GCP project** for the judge: `gemini-flash-latest` quota
  is per-project — a new GCP project = fresh 20-req/day. Update
  `GOOGLE_API_KEY` in `.env` + `fly secrets set` accordingly.
- **Cross-provider judge**: swap `JUDGE_MODEL_ID` to a Groq or
  OpenAI model. Note: agent + judge on the same provider re-introduces
  the self-judging bias `judge_prompt.py` was designed to avoid.

## Regression threshold (unchanged from Phase 4)

Per spec § 4 exit: any future run whose `correctness_mean` drops by
more than 0.5 vs a real baseline should fail CI (Phase 6+ addition).
Cannot be applied until a real baseline is captured.

## Meta

- **Experiment (LangSmith)**: `matchday-agent-phase4`. All attempted
  runs (blocked or not) surface as tagged traces in the UI.
- **Datasets (LangSmith)**:
  - `matchday-agent-anchor-cases` (15 examples, full)
  - `matchday-agent-anchor-cases-sample5` (5 examples, subset via `--limit 5`)
- **Judge model**: `google_genai:gemini-flash-latest` — see
  [judge_prompt.py](../src/matchday_agent/evals/judge_prompt.py) +
  [decisions.md § 4.6](../docs/decisions.md).
