# matchday-agent

Football-analyst agent that orchestrates the [`matchday-mcp`](https://github.com/reiorozco/matchday-mcp) server + Wikipedia RAG, streams reasoning over SSE, and persists conversation state in Supabase Postgres. Responds in English by default and mirrors the user's language when queried in Spanish, Portuguese, French, etc. Deployed on Fly.io.

**Live**: <https://matchday-agent.fly.dev> · **OpenAPI**: <https://matchday-agent.fly.dev/openapi.json> · **License**: MIT

---

## Live demo (60 s copy-paste)

```bash
UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')

# Metadata (name, version, model, 7 bound tools)
curl -sS https://matchday-agent.fly.dev/ | jq

# Non-streaming JSON round-trip (English default)
curl -sS -X POST https://matchday-agent.fly.dev/chat \
  -H 'Content-Type: application/json' \
  -H "X-Session-Id: $UUID" \
  -d '{"message":"How is Real Madrid doing in LaLiga?"}' | jq

# Streaming SSE — the primary consumption path for the frontend
curl -N -X POST https://matchday-agent.fly.dev/chat/stream \
  -H 'Content-Type: application/json' \
  -H "X-Session-Id: $UUID" \
  -d '{"message":"Compare Real Madrid vs Barcelona this season"}'
```

Reuse the same `X-Session-Id` to continue a conversation across requests — the checkpointer round-trips through Supabase Postgres. First request wakes the machine from `stopped` (~20 s cold start; ~2-3 s warm afterwards).

The agent mirrors your language — try `"message":"Compará Real Madrid vs Barcelona esta temporada"` and you'll get a Spanish response back with `(fuente: X)` citations instead of `(source: X)`.

---

## What's inside

- **LangGraph 1.2** — ReAct agent via `create_react_agent(version="v2")` with an `AsyncPostgresSaver` checkpointer on the same Supabase project as the RAG corpus.
- **7 tools** — 6 [`matchday-mcp`](https://github.com/reiorozco/matchday-mcp) tools bound over stdio (`get_standings`, `get_matches`, `get_top_scorers`, `find_team`, `get_team_matches`, `compare_teams`) + 1 in-repo RAG tool (`search_football_context`).
- **RAG v1** — 2 399 chunks of Wikipedia across 68 URLs (LaLiga + Premier League clubs + famous rivalries / finals) embedded with `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-d, Apache-2.0) into Supabase `pgvector`. HNSW cosine index. Swapped from `intfloat/multilingual-e5-large` (2.24 GB, 1024-d) after that model OOM-killed the 512 MB VM — full trade-off writeup in [decisions.md § 8.10](docs/decisions.md).
- **Zero-code provider swap** — `LLM_PROVIDER` env accepts `groq` (default, `llama-3.3-70b-versatile`) or `google_genai` (`gemini-flash-latest`) via LangChain's `init_chat_model` factory. Empirically validated: no code path branches on provider.
- **FastAPI + `sse-starlette`** — 5 endpoints, `slowapi` per-user rate limit (20 req/min via `Fly-Client-IP` header on POST endpoints; see [decisions.md § 8.11](docs/decisions.md)), CORS pinned to the Vercel frontend origin.
- **LangSmith** — every request auto-traced with `session_id`, detected `use_case`, `model`, and `env` metadata (no code changes; env-driven).
- **Fly.io** — single machine, `auto_stop_machines = 'stop'`, `shared-cpu-1x` / 1 GB (bumped from 512 MB post-audit; see [decisions.md § 8.10](docs/decisions.md)). Cost-safe scale-to-zero (verified: auto-stop fires ≈ 4 min after last inbound request).

### Anchor use cases (v1 shipped)

1. "How is X arriving to el Clásico?" — recent form + top scorers + Wikipedia rivalry context.
2. "Analyze Y's next match" — fixture + form + head-to-head.
3. "Compare A vs B this season" — statistical + form comparison.
4. "Which of the top 5 European leagues is most contested?" — parallel fetch of 5 top-league standings + spread computation. Exercises the parallel-tool-call pattern.
5. "LaLiga weekend summary" — matches + top scorers + storylines.

---

## Endpoints

| Method | Path              | Purpose                                   | Rate limit         |
|--------|-------------------|-------------------------------------------|--------------------|
| GET    | `/`               | App metadata (name, version, model, 7 tools) | unlimited       |
| GET    | `/health`         | Fly.io wake probe                         | unlimited          |
| GET    | `/openapi.json`   | Auto-generated OpenAPI schema             | unlimited          |
| POST   | `/chat`           | Non-streaming JSON (evals, tests)         | 20 req/min per IP  |
| POST   | `/chat/stream`    | SSE — primary path for the web            | 20 req/min per IP  |

**SSE event kinds**: `token` (per LLM chunk), `tool_call` (parallel emissions supported), `tool_result` (with `id` echoing `tool_call.id`), `final` (once per turn), `error` (terminates the stream). Full contract with field shapes: [docs/api-contract.md](docs/api-contract.md).

---

## Local quickstart

**Prerequisites**: Python 3.12+, [`uv`](https://docs.astral.sh/uv/) 0.9+, Node 20+ (for the `npx matchday-mcp` subprocess), Docker (optional).

```bash
git clone https://github.com/reiorozco/matchday-agent.git
cd matchday-agent
uv sync                 # installs 90 pinned deps + local package (~1-2 min first time)
cp .env.example .env    # fill in secrets — every var is documented inline
```

### CLI REPL (fastest local iteration)

```bash
uv run --env-file .env mda --session $(uuidgen)
```

Same session UUID resumes state; a new UUID starts fresh.

### HTTP server (mirrors production)

```bash
uv run --env-file .env uvicorn matchday_agent.app:app --reload --port 8000
```

Then re-run the live-demo curls against `http://localhost:8000` (no CORS constraint for curl).

### Docker (matches the shipped Fly.io image)

```bash
docker build -t matchday-agent .
docker run --rm --env-file .env -p 8080:8080 matchday-agent
```

Multi-stage build: `node:20-slim` (for the MCP subprocess) + `python:3.12-slim` + `uv 0.9.20`. Final image ≈ 183 MB. All 4 iterative Dockerfile fixes documented in [decisions.md § 5.3](docs/decisions.md).

### Evals runner

```bash
uv run --env-file .env evals
```

Reuses the LangSmith dataset `matchday-agent-anchor-cases` (15 examples). See [evals/baseline.md](evals/baseline.md) for the current status.

---

## Configuration

Every env is documented inline in [.env.example](.env.example). Critical ones:

| Env                          | Purpose                                                                         |
|------------------------------|---------------------------------------------------------------------------------|
| `LLM_PROVIDER` / `LLM_MODEL` | Provider swap. Default: `groq` / `llama-3.3-70b-versatile`.                     |
| `GROQ_API_KEY` / `GOOGLE_API_KEY` | Provider credentials (only the one matching `LLM_PROVIDER` is required).   |
| `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` + `LANGSMITH_PROJECT` | Auto-instrumentation (see [decisions.md § 0.9](docs/decisions.md)). |
| `DATABASE_URL`               | Supabase session-pooler DSN + `sslmode=require`. Used by both the checkpointer AND the RAG store. |
| `FOOTBALL_DATA_TOKEN`        | Inherited by the `npx matchday-mcp` subprocess.                                 |
| `ALLOWED_ORIGINS`            | Comma-separated CORS origins.                                                    |

**Never commit `.env`** (already `.gitignore`d). In production, all six real secrets live in `fly secrets set --stage`; the three non-secret runtime defaults (`LANGSMITH_TRACING`, `LLM_PROVIDER`, `LLM_MODEL`) sit in `fly.toml [env]`. Split rationale in [decisions.md § 5.8](docs/decisions.md).

---

## Architecture

```
web (Vercel) ── HTTP + SSE ──►  matchday-agent (Fly.io · iad · shared-cpu-1x)
                                 │
                                 ├── LangGraph ReAct agent (v2)
                                 │    ├── 6 MCP tools  ◄──► npx matchday-mcp (subprocess, stdio)
                                 │    └── 1 RAG tool   ◄──► Supabase pgvector (2 400 chunks · HNSW)
                                 │
                                 ├── AsyncPostgresSaver checkpointer
                                 │        └── Supabase Postgres (session pooler · ca-central-1)
                                 │
                                 └── LangSmith tracing (session_id + use_case + model + env)
```

Full design decisions (11 major sections, ~1 500 lines of "why"): [docs/decisions.md](docs/decisions.md).

The `AsyncExitStack` composition — `checkpointer` + `matchday_mcp_tools()` + `build_agent()` — is shared verbatim across three callers (CLI, FastAPI `lifespan`, evals runner). Any 4th caller triggers extraction to a `build_full_agent_stack()` factory ([decisions.md § 4.4](docs/decisions.md)).

---

## Observability

- **LangSmith project**: `matchday-agent`. Every graph run traced with `session_id`, `use_case`, `model`, `env` metadata (no code changes — auto-instrumented from envs per [decisions.md § 0.9](docs/decisions.md)).
- **Trace screenshot**: *(TODO — add `docs/screenshots/langsmith-trace.png` once a shareable view URL exists.)*

---

## Evals

Runner exposed as `uv run --env-file .env evals`. Dataset `matchday-agent-anchor-cases` in LangSmith (15 examples = 5 anchor cases × 3 phrasings). Evaluators:

| Evaluator        | Signal                                                              |
|------------------|---------------------------------------------------------------------|
| `correctness`    | LLM-as-judge on Gemini, scoring answers against `reference_summary` on a 1-5 scale |
| `tool_selection` | Set-overlap between called tools and `expected_tools[]`             |
| `latency`        | Client-side wall-clock, p50 / p95                                    |

Baseline status: [evals/baseline.md](evals/baseline.md) — infrastructure verified end-to-end (15 traces uploaded, all 3 evaluators registered, `error_handling='log'` path exercised). Quantitative scores pending free-tier daily-quota reset — details in [decisions.md § 4.3](docs/decisions.md).

---

## Deploy

Fly.io, single machine, `auto_stop_machines = 'stop'` (scale-to-zero when idle), region `iad`. Verified live behavior:

- Cold start `/health`: **20.79 s** (2.5× over the < 8 s spec target; documented as acceptable for demo).
- Warm `/`: **0.41 s**.
- Auto-stop: fires **≈ 4 min** after last external request.
- SSE contract: byte-verified in production (all 5 event kinds).
- CORS: Vercel origin allowed; unlisted origins receive `HTTP 400` with no `Access-Control-Allow-Origin` header.

Full deploy walkthrough + 4-fix Dockerfile iteration history + auto-start/auto-stop evidence: [decisions.md § 5.1–5.9](docs/decisions.md).

Redeploy after a code change:

```bash
fly deploy
```

Update a runtime env (triggers redeploy):

```bash
fly secrets set --stage LLM_PROVIDER=google_genai LLM_MODEL=gemini-flash-latest
fly deploy   # or `fly secrets deploy` if config is otherwise unchanged
```

---

## Known limitations

Documented for reviewer honesty:

- **Eval drift**: [`evals/anchor_cases.jsonl`](evals/anchor_cases.jsonl) references specific league standings (points, positions) that age with the live football-data.org data. Baseline scores in [`evals/baseline.md`](evals/baseline.md) may show apparent regression that's actually just data drift, not real quality loss.
- **Cold start ~20 s on first request**: Fly auto-stops the machine after ~4 min idle to save cost. First inbound wakes it (Python + fastembed model load + MCP subprocess = 15-20 s); warm requests ~2-3 s. Deliberate cost/latency trade-off for a portfolio demo — flip to `min_machines_running = 1` in [`fly.toml`](fly.toml) for real traffic.
- **Groq free tier daily token quota**: 100 k tokens/day on `llama-3.3-70b-versatile`. When hit, the endpoint returns a friendly `{"code": "RateLimit", "message": "Daily token quota reached..."}` payload ([decisions.md § 8.8](docs/decisions.md)) — no cryptic 500s. Recovery ~15 min; swap to Gemini via `fly secrets set LLM_PROVIDER=google_genai LLM_MODEL=gemini-flash-latest --app matchday-agent`.
- **RAG embedder trade-off**: swapped from `intfloat/multilingual-e5-large` (1024-dim, 2.24 GB) to `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, ~220 MB) after the larger model OOM-killed the 512 MB VM ([decisions.md § 8.10](docs/decisions.md)). ~5-15% retrieval-quality drop for a ~10× memory reduction — worth it to keep RAG functional on the free tier.
- **~~Supabase RLS disabled on public tables~~** — ✅ resolved 2026-07-29: RLS enabled on all 5 public tables with `service_role`-only policies as defense-in-depth ([db/migrations/001_enable_rls_public_tables.sql](db/migrations/001_enable_rls_public_tables.sql), [decisions.md § 8.14](docs/decisions.md)). Backend continues to use the `postgres` role via `DATABASE_URL`, which bypasses RLS — zero-code-change fix.

---

## Related repos

- [`reiorozco/matchday-mcp`](https://github.com/reiorozco/matchday-mcp) — Node/TypeScript MCP server (6 tools over stdio, published as `matchday-mcp` on npm).
- [`reiorozco/matchday-mcp-web`](https://github.com/reiorozco/matchday-mcp-web) — Svelte 5 + Tailwind v4 frontend consuming this agent's SSE contract. Live at <https://matchday-mcp-web.vercel.app>.

---

## License

MIT.
