# Phase 0 — Closed decisions

Snapshot date: 2026-07-25. Every decision below is grounded in the
research reports produced by four parallel Context7/librarian passes
(LangGraph stack, MCP Python SDK, FastAPI SSE + Postgres/pgvector,
Fly.io deploy + Supabase MCP).

This file is the **single source of truth** for Phase 0 outcomes. The
spec (`../matchday-mcp/specs/004-langgraph-agent.md`) links here rather
than duplicating.

---

## 0.1 — Pinned versions

Locked into `pyproject.toml`. Python 3.12+, managed by `uv` 0.9.20.

### Runtime dependencies

| Package                          | Version               | Purpose                                      |
|----------------------------------|-----------------------|----------------------------------------------|
| `langgraph`                      | `==1.2.9`             | State graph + `create_react_agent`           |
| `langgraph-checkpoint-postgres`  | `==3.1.0`             | `AsyncPostgresSaver` (uses psycopg 3)        |
| `langchain`                      | `==1.3.14`            | High-level chains + `init_chat_model`        |
| `langchain-core`                 | `==1.5.1`             | Peer of langchain / mcp-adapters             |
| `langchain-groq`                 | `==1.1.3`             | Groq provider (primary)                      |
| `langchain-google-genai`         | `==4.3.1`             | Gemini provider (swap via env)               |
| `langsmith`                      | `==0.10.10`           | Tracing + evals SDK                          |
| `mcp`                            | `>=1.28.1,<2`         | Python MCP SDK (v1 stable; v2 is beta)       |
| `langchain-mcp-adapters`         | `==0.3.0`             | MCP tools → LangChain `BaseTool`             |
| `fastapi`                        | `==0.140.0`           | HTTP framework                               |
| `uvicorn[standard]`              | `==0.51.0`            | ASGI server + uvloop + httptools             |
| `sse-starlette`                  | `>=0.3.0`             | `EventSourceResponse` (auto X-Accel header)  |
| `pgvector`                       | `==0.5.0`             | pgvector bindings (`register_vector_async`)  |
| `psycopg[binary,pool]`           | `==3.3.4`             | Postgres v3 driver + async pool              |
| `slowapi`                        | `==0.1.10`            | Per-IP rate limit (async/SSE-compatible)     |
| `httpx`                          | `>=0.28.1`            | Test client (also pulled by FastAPI extras)  |
| `Wikipedia-API`                  | `==0.15.0`            | RAG ingestion (actively maintained fork)     |

### Dev dependencies

| Package             | Version   | Purpose                    |
|---------------------|-----------|----------------------------|
| `pytest`            | `>=8.0`   | Test runner                |
| `pytest-asyncio`    | `>=0.24`  | Async test support         |
| `ruff`              | `>=0.7`   | Lint + format              |
| `basedpyright`      | `>=1.20`  | Strict type-checking       |

### LLM model defaults (env-swappable)

Providers are swappable via `LLM_PROVIDER` + `LLM_MODEL` env. Defaults
locked in `.env.example`:

| Provider (`LLM_PROVIDER`)   | Default `LLM_MODEL`             | Notes                                                                |
|-----------------------------|---------------------------------|----------------------------------------------------------------------|
| `groq` (primary)            | `llama-3.3-70b-versatile`       | Tool-calling native, free tier robust. **Do NOT default to Mixtral 8x7b — deprecated by Groq.** Consider `moonshotai/kimi-k2-instruct` as A/B in Phase 1. |
| `google_genai` (fallback)   | `gemini-3.5-flash`              | Pinned to 3.5 Flash. Alternative: `gemini-flash-latest` (alias) for auto-updates. **Gemini 2.5 line is closed to NEW API accounts as of 2026** — the `list_models` API still lists them but calls return 404. Verified 2026-07-26 with this project's key. |

The unified `init_chat_model` factory autodetects provider from the
model string prefix (`"groq:..."`, `"google_genai:..."`), so the code
never branches on provider — the branch is at env-read time only.

**Response-shape gotcha for Phase 1**: Groq returns `AIMessage.content
= str`; Gemini 3.x returns `AIMessage.content = list[dict]` with
`extras.signature` (thought-signature for reasoning caching). LangGraph
normalizes both when routing through `create_react_agent`, but if we
ever need to serialize the raw `content` (evals, logs), branch on
`isinstance(msg.content, list)`.

### Version-compat notes

- No known-bad pairings across the runtime set as of 2026-07-25.
- `langchain>=1.3.14` pins `langchain-core>=1.4.7,<2.0.0`; `1.5.1`
  satisfies this and the `langchain-mcp-adapters==0.3.0` peer
  constraint (`langchain-core>=1.3.3,<2.0.0`).
- `langgraph-checkpoint-postgres==3.1.0` requires
  `psycopg>=3.2.0` + `psycopg-pool>=3.2.0`; `psycopg[binary,pool]==3.3.4`
  is a superset and installs both.
- **Known-bad** to avoid: `langgraph<1.2.0` with
  `langgraph-checkpoint-postgres>=3.0.0` (incompatible checkpointer
  API); `langchain<1.3.0` with `langchain-groq>=1.1.0` (missing
  provider support in `init_chat_model`); `langsmith<0.10.0` with
  `langgraph>=1.2.0` (tracing metadata format mismatch).
- `mcp` v2 targets 2026-07-27 as a beta rework. **Do not upgrade to v2
  during v1 of this agent**; revisit in Phase 4.

---

## 0.2 — MCP client → matchday-mcp

**Pattern**: official `mcp` Python SDK's `stdio_client` spawns
`npx -y matchday-mcp` as a subprocess and speaks JSON-RPC over stdio.

**Import paths** (confirmed against `python-sdk` current):

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
```

**Tool binding**: use `langchain-mcp-adapters`'s `load_mcp_tools(session)`
which returns a `list[BaseTool]` compatible with `create_react_agent`.
It's actively maintained (0.3.0, last commit 2026-07-25) and stable
enough for a portfolio project. If it stalls in the future, replacing
it with a ~25 LOC manual wrapper over `StructuredTool` is trivial.

**Docker requirement**: `stdio_client` literally execs `command`, so
the container **must** ship Node 20+. Multi-stage COPY from
`node:20-slim` into `python:3.12-slim` keeps the image ~330 MB.

**Session lifetime**: **persistent session** for the FastAPI process
(Option B). One MCP session spawned on `lifespan` startup, reused for
every request. First-request cost ~100 ms (spawn + handshake);
subsequent tool calls <10 ms. Per-request spawn (Option A) is only
justified for stateless / serverless deployments — that's not us.

**FOOTBALL_DATA_TOKEN**: passed into `StdioServerParameters.env`; the
subprocess inherits PATH/HOME via
`mcp.client.stdio.get_default_environment()` (merge, not replace).

Smoke script: `../scripts/mcp_smoke.py` — spawns the server, lists the
6 tools, calls `get_standings(competition="PD")`, prints the result,
cleans up gracefully.

---

## 0.3 — Postgres client + pgvector: **raw psycopg 3, no SQLAlchemy**

**Decision**: `psycopg[binary,pool]==3.3.4` + `pgvector==0.5.0`.

**Rationale (three bullets)**:

1. `langgraph-checkpoint-postgres` uses psycopg 3 under the hood.
   Using the same driver eliminates version conflicts and connection
   pool fragmentation. SQLAlchemy adds an indirection that buys
   nothing at v1 (single table).
2. Prepared statements + pooling: psycopg 3's `AsyncConnectionPool`
   with `configure=register_vector_async` gives us type-safe vector
   ops with zero ORM tax. SQLAlchemy's async layer can mask prepared
   statement lifecycle issues under Supavisor.
3. One table (`documents`), no migrations tooling, no ORM benefit at
   this scale. ~20 LOC vs. SQLAlchemy declarative boilerplate.

**Do not install** `sqlalchemy` or the `sqlalchemy` skill from the
autoskills registry. If a future need arises (users table, auth,
multi-entity domain), revisit — not blocking for v1.

**Async pgvector pattern** (paste into `src/matchday_agent/rag.py`
when Phase 2 lands):

```python
from psycopg import AsyncConnectionPool
from pgvector.psycopg import register_vector_async
from pgvector import Vector

async def _configure(conn):
    await register_vector_async(conn)

pool = AsyncConnectionPool(
    conninfo=os.environ["DATABASE_URL"],
    configure=_configure,
    min_size=2,
    max_size=10,
)

async def similar(query_embedding: list[float], k: int = 5):
    async with pool.connection() as conn:
        rows = await conn.execute(
            """
            SELECT id, source_url, title, chunk_idx, content,
                   embedding <=> %s AS distance
            FROM documents
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (Vector(query_embedding), Vector(query_embedding), k),
        )
        return await rows.fetchall()
```

---

## 0.4 — LangGraph Postgres checkpointer

**API** (`langgraph-checkpoint-postgres==3.1.0`):

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
    await checkpointer.setup()  # idempotent, safe on every boot
    graph = build_graph()
    app = graph.compile(checkpointer=checkpointer)
```

**Sync variant** (only if we ever need it — we do not for v1):

```python
from langgraph.checkpoint.postgres import PostgresSaver
with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
    checkpointer.setup()
```

**Thread namespace**: `thread_id = X-Session-Id` header (UUID generated
client-side in the web app and persisted in `localStorage`). No user
auth in v1. Format validated (UUID v4) on request entry.

**`create_react_agent` signature** (`langgraph.prebuilt`) accepts the
checkpointer directly:

```python
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(
    model=model,                # BaseChatModel from init_chat_model
    tools=mcp_tools + [rag_tool],
    checkpointer=checkpointer,
    version="v2",               # default; v1 is deprecated
)
```

**Supabase pooler compatibility** — this is the ONE reliability gotcha
of the whole stack. Supavisor uses DIFFERENT PORTS to switch modes on
the same pooler host:

| DSN kind                                        | Host                                             | Port | Username                | Prepared stmts | Recommendation |
|-------------------------------------------------|--------------------------------------------------|------|-------------------------|----------------|----------------|
| Direct connection                               | `db.<REF>.supabase.co`                           | 5432 | `postgres`              | Full           | ⚠️ IPv6-only in current Supabase; Fly.io outbound to IPv6 works but is a gotcha |
| **Session pooler (Supavisor)** — **v1 default** | `aws-0-<REGION>.pooler.supabase.com`             | 5432 | `postgres.<REF>`        | Full           | ✅ Works from anywhere (IPv4+IPv6); supports prepared statements |
| Transaction pooler (Supavisor)                  | `aws-0-<REGION>.pooler.supabase.com`             | 6543 | `postgres.<REF>`        | Edge cases with prepared statements | ⚠️ Do NOT use for checkpointer or pgvector at v1 |

**v1 pinned choice**: **session pooler at port 5432** on
`aws-0-<REGION>.pooler.supabase.com`, username `postgres.<REF>`.
Append `?sslmode=require` (Supabase enforces TLS).

For the concrete `matchday-dev` project (ref `vdggittczhvvszguqxez`,
region `ca-central-1`):

```
postgresql://postgres.vdggittczhvvszguqxez:<PASSWORD>@aws-0-ca-central-1.pooler.supabase.com:5432/postgres?sslmode=require
```

Password lives in `.env` locally and in `fly secrets set` in prod.
Verify the exact host once against the dashboard's "Get Connected →
Session pooler" widget — Supabase has renamed hosts historically.

Smoke script: `../scripts/checkpointer_smoke.py`.

---

## 0.5 — FastAPI SSE contract for the frontend

Full contract in `./api-contract.md`. Summary of decisions:

- Streaming source: LangGraph `astream_events(version="v2")`.
  - **v2 chosen over v3 for v1 of this agent**: v2 has the well-known
    filter-by-event-type pattern (`on_chat_model_stream`, `on_tool_start`,
    `on_tool_end`) that maps cleanly to the frozen SSE event shape.
    v3 (typed projections `.messages` / `.tool_calls` / `.output`) is
    GA in LangChain 1.3.14 but requires concurrent consumption; the
    migration is a Phase 3 stretch, not a Phase 0 commitment.
- Response wrapper: `sse-starlette`'s `EventSourceResponse`.
- Buffering off headers (both Fly.io and Vercel edge require these):
  - `Cache-Control: no-cache`
  - `X-Accel-Buffering: no`
  - `Connection: keep-alive`
- Rate limit: `slowapi` @ 20 req/min per IP on `/chat` and
  `/chat/stream`; `/health` unlimited.
- CORS: `ALLOWED_ORIGINS` env, comma-separated. Prod set to
  `https://matchday-mcp-web.vercel.app`; dev adds `http://localhost:5173`.

---

## 0.6 — Deploy target on Fly.io

Draft artifacts committed to the repo:

- `../Dockerfile` — multi-stage `node:20-slim` → `python:3.12-slim`
  + `uv 0.9.20` + non-root `appuser`. Build-time sanity check runs
  `npx -y matchday-mcp --version` (fail-fast if the package can't be
  resolved from npm). Container listens on `0.0.0.0:8080`.
- `../fly.toml` — `primary_region = "mia"` (default; `iad` / `sea`
  documented as alternatives). `[http_service]` with
  `auto_stop_machines = "stop"`, `auto_start_machines = true`,
  `min_machines_running = 0`. Concurrency: `hard_limit = 20`,
  `soft_limit = 10`. Health check hits `/health` with a 15 s grace
  period. `[[vm]]` `shared-cpu-1x`, `memory = "512mb"` (comment
  documents the bump to `1gb` if the Node subprocess + pgvector
  queries pressure it).

### Secrets (set via `fly secrets set` — never committed)

| Name                  | Purpose                                          |
|-----------------------|--------------------------------------------------|
| `GROQ_API_KEY`        | Groq API auth                                    |
| `LANGSMITH_API_KEY`   | LangSmith tracing                                |
| `LANGSMITH_PROJECT`   | LangSmith project name (default `matchday-agent`)|
| `DATABASE_URL`        | Supabase direct / session pooler DSN + sslmode   |
| `FOOTBALL_DATA_TOKEN` | Inherited by `npx matchday-mcp` subprocess       |
| `ALLOWED_ORIGINS`     | Comma-separated CORS origins                     |

Set them all in one command (triggers a redeploy):

```bash
fly secrets set \
  GROQ_API_KEY="..." \
  LANGSMITH_API_KEY="..." \
  LANGSMITH_PROJECT="matchday-agent" \
  DATABASE_URL="postgresql://postgres.vdggittczhvvszguqxez:<PASS>@aws-0-ca-central-1.pooler.supabase.com:5432/postgres?sslmode=require" \
  FOOTBALL_DATA_TOKEN="..." \
  ALLOWED_ORIGINS="https://matchday-mcp-web.vercel.app"
```

### Fly.io + SSE — known gotcha

**Idle SSE streams do NOT keep the machine awake.** Fly Proxy scores
"load" on inbound HTTP, not outbound streaming. If the agent has no
new incoming requests for 5–10 min while streaming a slow response,
the machine gets stopped mid-stream.

Mitigations (revisit if we see it in practice):

- v1: shrug — our anchor use cases complete in < 30 s, well under any
  idle timeout.
- v2: if we add long-running streams, either disable auto-stop
  (`auto_stop_machines = "off"`) or split streaming into a separate
  process group (no `[http_service]`).

`flyctl` is **not** installed on the workstation yet — deferred to
Phase 5 (`brew install flyctl`).

---

## 0.7 — Supabase MCP for dev

`.mcp.json` at repo root, HTTP transport, project-scoped, read-only,
`features=database,docs`:

```json
{
  "mcpServers": {
    "supabase-matchday-dev": {
      "type": "http",
      "url": "https://mcp.supabase.com/mcp?project_ref=<PROJECT_REF>&read_only=true&features=database,docs"
    }
  }
}
```

**Naming**: `supabase-matchday-dev` (descriptive, project-explicit)
rather than the bare `supabase`. Keeps future multi-project setups
(e.g. `supabase-matchday-prod`) unambiguous.

**Consequence for existing `matchday-agent/.claude/settings.local.json`**:
it disabled a server literally named `supabase`. Since our entry is
named `supabase-matchday-dev`, the disable was inert. **Also cleared
that array** to keep the settings file honest.

**Feature flags** (defaults in URL above are safe for dev):

| Feature       | Effect                                      |
|---------------|---------------------------------------------|
| `database`    | Run SQL, manage tables, apply migrations    |
| `docs`        | Search Supabase docs                        |
| `debugging`   | Read service logs + advisors (optional)     |
| `development` | API URLs, generate TS types (optional)      |
| `functions`   | Edge functions (skip — has write ops)       |
| `branching`   | Dev branches (skip — paid feature)          |
| `account`     | Auto-disabled when `project_ref` is set     |
| `storage`     | Off by default                              |

**Authentication**: first-time use opens a browser → Supabase OAuth
consent → scoped token cached locally. For CI/headless runs, set
`SUPABASE_ACCESS_TOKEN` env and add
`"headers": {"Authorization": "Bearer ${SUPABASE_ACCESS_TOKEN}"}` to
the entry. Not needed for local dev.

**`<PROJECT_REF>` captured** (2026-07-25):

| Field       | Value                                        |
|-------------|----------------------------------------------|
| Name        | `matchday-dev`                               |
| project_ref | `vdggittczhvvszguqxez`                       |
| Region      | `ca-central-1` (Canada Central)              |
| Instance    | `t3.nano` (Supabase free tier)               |
| Project URL | `https://vdggittczhvvszguqxez.supabase.co`   |

Baked into `.mcp.json` and `.env.example`. The DB password is NOT
recorded here — user pastes it directly into their local `.env` and
into `fly secrets set` for prod.

---

## 0.8 — Skills (manual install from validated registry)

Per the user's directive (skills.sh registry, validated):

| Skill                                | Source              | Install when      |
|--------------------------------------|---------------------|-------------------|
| `supabase-postgres-best-practices` ⭐ | supabase (official) | Phase 0 (now)     |
| `fastapi-python`                     | mindrally           | Phase 0 (now)     |
| `python-testing-patterns`            | wshobson            | Phase 0 (now)     |
| `pydantic`                           | pydantic/skills (official) | Phase 0 (now)     |
| ~~`sqlalchemy`~~                     | ~~bobmatnyc~~       | **Skipped** — 0.3 chose raw psycopg |

Core agentic (LangGraph / LangSmith / MCP Python) has no autoskills
entry — the four Phase 0 librarian runs are the substitute reference.
For future depth (Phase 1+), continue calling `librarian` +
Context7 IDs recorded in section 0.1.

**Install path** left to the user (registry credentials + `skills.sh`
CLI are user-scoped). Verify installs land in `.claude/skills/` after
the fact.

---

## 0.9 — LangSmith project setup

- Project name: `matchday-agent` (env `LANGSMITH_PROJECT`).
- Tracing on via envs (**no code changes** — LangChain / LangGraph
  auto-instrument when both vars are set):
  ```
  LANGSMITH_TRACING=true
  LANGSMITH_API_KEY=ls_...
  ```
- Other envs recognized by the SDK v0.10.10:
  `LANGSMITH_ENDPOINT` (defaults to `https://api.smith.langchain.com`),
  `LANGSMITH_TRACING_MODE` (`langsmith` | `otel` | `hybrid`),
  `LANGSMITH_TRACING_SAMPLING_RATE` (0.0–1.0).
- Custom metadata attached with the `@traceable(metadata={...})`
  decorator on any function we want tagged with `session_id`,
  `use_case`, `model`, `env`.
- Redaction rule for accidental key leaks: document a review step in
  Phase 4 evals, not a runtime filter (keys shouldn't be in payloads
  in the first place).

Verification (Phase 0 exit): hello-world graph run appears in
LangSmith with the expected tags. **Requires** the user to create a
LangSmith account + project + API key. Not blocking to write the code,
blocking to test end-to-end.

---

## Open items requiring the user

Before Phase 1 can execute end-to-end:

1. ~~**Supabase project ref**~~ — ✅ captured (`vdggittczhvvszguqxez`,
   region `ca-central-1`); baked into `.mcp.json` and `.env.example`.
2. **Supabase DB password** — for `DATABASE_URL`. User pastes into
   local `.env` and later into `fly secrets set`. Never through chat.
3. **Groq API key** — free tier account at console.groq.com.
4. **LangSmith API key + project** — free tier at smith.langchain.com;
   create project `matchday-agent`.
5. **FOOTBALL_DATA_TOKEN** — already have (from matchday-mcp Phase 3).
6. **`skills.sh` runs** — install the four skills above manually.
7. **`brew install flyctl`** — deferred to Phase 5 kickoff.

All of the above are recorded (with `TODO` markers) inside
`.env.example` for onboarding.

---

## Evidence & sources

Every claim above is grounded in one of these:

- **LangGraph 1.2.9** — https://github.com/langchain-ai/langgraph
  (`libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py`,
  `libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py`).
  Context7 id: `/langchain-ai/langgraph`.
- **LangChain 1.3.14** — https://github.com/langchain-ai/langchain
  (`libs/langchain_v1/langchain/chat_models/base.py`).
  Context7 id: `/websites/langchain_oss_python_langchain`.
- **LangSmith 0.10.10** — https://github.com/langchain-ai/langsmith-sdk
  Context7 id: `/langchain-ai/langsmith-sdk`.
- **MCP Python SDK 1.28.1** — https://github.com/modelcontextprotocol/python-sdk
  Context7 id: `/websites/py_sdk_modelcontextprotocol_io_v2`.
- **langchain-mcp-adapters 0.3.0** — https://github.com/langchain-ai/langchain-mcp-adapters
  Context7 id: `/langchain-ai/langchain-mcp-adapters`.
- **FastAPI 0.140.0** — Context7 id: `/websites/fastapi_tiangolo`.
- **sse-starlette** — Context7 id: `/sysid/sse-starlette`.
- **pgvector Python 0.5.0** — Context7 id: `/pgvector/pgvector-python`.
- **psycopg 3.3.4** — Context7 id: `/websites/psycopg_psycopg3`.
- **slowapi** — Context7 id: `/laurents/slowapi`.
- **Fly.io** — Context7 id: `/superfly/docs`.
- **Supabase MCP** — https://supabase.com/docs/guides/ai-tools/mcp
  and https://github.com/supabase/mcp.
- **Claude Code MCP config** — Context7 id: `/websites/code_claude`.

---

# Phase 1 — Outcomes

Snapshot date: 2026-07-26. Phase 1 shipped in commit `1f46185` on
`matchday-agent` main. Full closing notes with runtime evidence live
in the spec (`~/Dev/matchday-mcp/specs/004-langgraph-agent.md §
Phase 1`); this section is the source of truth for the decisions that
lock choices for Phase 2 onward.

---

## 1.1 — LLM default confirmed: Groq `llama-3.3-70b-versatile`

Locked in `.env.example` and validated across the 5 anchor use cases:

- Tool-calling: native, robust. Emits parallel tool calls in a single
  assistant response when instructed to (see § 1.2).
- Response shape: `AIMessage.content = str` (matches the response-shape
  gotcha noted in § 0.1). The CLI's `_extract_chunk_text` handles both
  Groq's `str` and Gemini 3.x's `list[dict]` shapes, so provider swap
  via `LLM_PROVIDER=google_genai` remains zero-code.

**Kimi K2 A/B deferred to Phase 4** (LangSmith evals). Bench inside
this repo is a stretch; the free tier of `llama-3.3-70b-versatile` is
adequate for v1 shipping.

---

## 1.2 — `SYSTEM_PROMPT` is a Phase 1 deliverable, not a later stretch

**Empirical finding**: Groq `llama-3.3-70b-versatile` (and by
extension, any model < ~200B params on similar training) does NOT
reliably emit parallel tool calls or use complementary tools without
explicit prompting. Discovered by running the 5 anchor cases against
a minimal prompt — case #4 fetched only 2 of the 5 top leagues,
failing the parallelization exercise the spec mandates.

**Fix**: added three directives to `SYSTEM_PROMPT` in
`src/matchday_agent/prompts/system.py`:

1. **Parallel tool calls** — "when a question spans N entities or N
   competitions, emit N tool calls in the SAME assistant response so
   LangGraph runs them in parallel". Example given inline for the
   5-leagues case.
2. **Question → tools coverage guide** — maps common Spanish football
   queries ("cómo llega X al clásico", "próximo partido de X",
   "compará A vs B", "cuál liga está más disputada", "resumen del
   fin de semana") to the exact tool combinations the model must
   call, so it doesn't dismiss a question as unanswerable by using
   only one tool.
3. **Try-alternative-tools rule** — "if one tool returns empty or
   errors, try a DIFFERENT tool that could cover the same
   information before telling the user you cannot answer". Prevents
   early surrender on `get_team_matches` when `get_matches` is the
   actual fixture source.

**Prompt language**: English (instructions). Response language:
Spanish, neutral Latin American register, enforced in the prompt
body. Full text in `src/matchday_agent/prompts/system.py`.

**Rule of thumb for Phase 2+**: any behavior we expect from the
agent must be either (a) explicit in the prompt, (b) demonstrated by
a few-shot example in the prompt, or (c) a hard-coded guardrail in
the graph. LangGraph itself does NOT enforce behavior — the LLM does
what the prompt tells it, no more.

---

## 1.3 — `[tool.basedpyright] typeCheckingMode = "standard"`

Locked in `pyproject.toml`. Rationale in the file's inline comment;
short version: basedpyright's default `"recommended"` mode is a
superset of pyright's `"standard"` with extra rules
(`reportAny`, `reportExplicitAny`, `reportUnknownVariableType`,
`reportUnknownMemberType`, `reportUnknownArgumentType`,
`reportUnusedCallResult`, `reportImplicitStringConcatenation`,
`reportDeprecated`, `reportMissingTypeStubs`) that fire ~50 times on
the `langchain` / `langgraph` / `langchain-mcp-adapters` ecosystem
because those libraries leak `Unknown` and `Any` through their
public generics.

Dropping to pyright's `"standard"` baseline still catches:

- Missing imports.
- Wrong argument types on OUR code.
- Undeclared generic type arguments on OUR code (this is why we
  type `checkpointer: BaseCheckpointSaver[Any]` and
  `CompiledStateGraph[Any, Any, Any, Any]` in `graph.py`).
- Deprecated symbols we import (informational).

**Do NOT bump back to `"recommended"`** without a strategy for the
ecosystem noise (stub packages for langchain/langgraph, or a long
list of file-scoped `# pyright: ignore` directives — both worse than
the current setup).

---

## 1.4 — RAG tool intentionally NOT stubbed in Phase 1

The spec drafted "the 1 RAG tool (added in Phase 2; stubbed here)".
Decision: **do not stub**. A tool advertised in the system prompt
that returns nothing useful degrades tool-selection reasoning — the
model tries it, gets nothing, and either gives up early or distrusts
the whole tool set.

**Contract preserved for Phase 2**: the RAG tool arrives via the
same `create_react_agent(..., tools=[...])` binding site in
`src/matchday_agent/graph.py`, no changes needed to `cli.py` or
`tools/mcp_tools.py`. To ship it:

1. Add `search_football_context(query, k=5)` as a LangChain
   `BaseTool` (likely under `src/matchday_agent/tools/rag.py`).
2. Append it to the `tools` list in `graph.py`.
3. Add the corresponding paragraph to the coverage guide in the
   system prompt so the model knows when to reach for it (rivalry,
   history, "legendary" style questions).

---

## 1.5 — CLI streaming pattern shared with Phase 3 SSE

The `mda` REPL's streaming implementation in `src/matchday_agent/cli.py`
uses `agent.astream_events(..., version="v2")` and filters the same
`on_chat_model_stream` + `on_tool_start` events that Phase 3's
`EventSourceResponse` will consume (per § 0.5). This is deliberate:
the REPL is not throwaway — it's the local mirror of the production
SSE contract. When Phase 3 wires FastAPI, `_stream_turn`'s event
handling code can be lifted almost verbatim into the event serializer,
keeping the CLI and the web on the same behavior.

**Do not diverge** the REPL's event handling from the SSE contract in
Phase 3 — instead, extract the shared logic into a small utility if
the shape between CLI-print and SSE-emit needs to fork.

---

# Phase 2 — Outcomes

Snapshot date: 2026-07-26. Phase 2 shipped on `matchday-agent` main.
Wikipedia RAG corpus lives in Supabase `public.documents` (2400 rows
spanning 68 unique Wikipedia URLs — 50 EN + 18 ES). Full closing notes
with runtime evidence live in the spec
(`~/Dev/matchday-mcp/specs/004-langgraph-agent.md § Phase 2`); this
section is the source of truth for the decisions that lock choices for
Phase 3+.

---

## 2.1 — Embedder locked: `intfloat/multilingual-e5-large` via fastembed

**Decision**: 1024-dim, MIT license, multilingual (~100 langs), local
ONNX inference via `fastembed>=0.7.1`. No API keys, no rate limits, no
billing risk. Cached at `~/.cache/fastembed/`; first-run download
~2.24 GB.

**Empirical pivot from the initial librarian recommendation**: the
research pass recommended `BAAI/bge-m3` via fastembed. Runtime check
(`TextEmbedding.list_supported_models()`) revealed BGE-M3 is NOT in
fastembed's catalog — it requires the separate `FlagEmbedding` library
because of its multi-vector modes. Pivoted to `multilingual-e5-large`,
same 1024d, native to fastembed's qdrant-hosted catalog.

**Chunk-size trade-off**: E5-large truncates at 512 tokens. With the
"passage: " prefix (~2 tokens) injected by `fastembed.passage_embed`,
we set the chunker to 480 tokens (see § 2.2) to leave headroom. Chunks
larger than 480 would silently lose their tail after tokenization.

**Fastembed 0.7 pooling warning**: startup emits a UserWarning
suggesting to pin `fastembed==0.5.1` to preserve the "CLS embedding"
pooling that older E5-large uses. Fastembed 0.7+ switched to mean
pooling. **Ignored**: mean pooling is the current
sentence-transformers default and works well in practice; the warning
is cosmetic drift, not a correctness bug.

**Query vs passage APIs** (from `src/matchday_agent/rag/embedder.py`):

```python
from fastembed import TextEmbedding

model = TextEmbedding(model_name="intfloat/multilingual-e5-large")

passage_vecs = list(model.passage_embed(texts, batch_size=32))
query_vec = list(model.query_embed([query]))[0]
```

Fastembed injects the E5 required prefixes internally; never inject
them manually.

---

## 2.2 — Ingestion pipeline

**Library**: `Wikipedia-API==0.15.0` (already pinned from Phase 0).
Kept over `langchain_community.WikipediaLoader` which is broken in
2026 — it delegates to the unmaintained `goldsmith/Wikipedia` package
that Wikimedia rate-limited due to a non-compliant User-Agent.

**Sync-vs-async choice**: `wikipediaapi.AsyncWikipedia` exists in
0.15.0 but the ingest script uses the sync `Wikipedia` class wrapped
with `asyncio.to_thread`. Simpler, well-tested behavior; ingestion is
a one-shot script where async ergonomics don't materially help.

**User-Agent** (per Wikimedia Foundation policy, 2024+):

```
matchday-agent/0.1 (https://github.com/reiorozco/matchday-agent/issues) Wikipedia-API/0.15.0
```

GitHub issues URL alone (no email) is policy-compliant and doesn't
leak private contact info.

**Chunking** — locked in `scripts/ingest_wikipedia.py`:

- `RecursiveCharacterTextSplitter.from_tiktoken_encoder(encoding_name="cl100k_base")`
- `chunk_size=480 tokens` (NOT 512 — leaves headroom for E5's
  "passage: " prefix inside the 512-token truncation limit)
- `chunk_overlap=64 tokens` (~13%)

Do NOT default to `len` as the length function — that measures
characters, not tokens, and 480 chars is ~100-150 tokens (way too
small). `from_tiktoken_encoder` swaps in the tiktoken byte-pair
counter, which is what the 480/64 numbers are calibrated against.

**Corpus (v1)**: 60 pages across EN + ES:

- 20 LaLiga 2024-25 clubs (EN + ES)
- 20 Premier League 2024-25 clubs (EN only)
- 10 famous derbies + Champions League finals (EN only)

Result: **2400 chunks** (~40 per page average). EN pass 1165 chunks,
ES pass 1235 chunks (ES articles for big clubs like Real Madrid /
Atlético Madrid tend to be longer than their EN counterparts).

**One title mismatch**: `Athletic Bilbao` is missing on ES wiki
(the page there is `Athletic Club`). Not blocking for v1; a future
alias-fallback layer inside the ingester would fix it.

---

## 2.3 — Schema + migration path

**Table**: `public.documents`, 11 columns, `embedding vector(1024)`.
Full DDL in `db/schema.sql`.

Key column decisions:

- `section_title TEXT` (nullable, NOT populated in v1) — placeholder
  for a Phase 4+ enhancement that chunks by Markdown headers instead
  of flat text.
- `revision_id BIGINT` (nullable, NOT populated in v1) —
  Wikipedia-API 0.15.0 does not expose `revision_id` on the default
  page object. Left in the schema for future incremental-update
  workflows.
- `UNIQUE (source_url, chunk_idx)` — enables the upsert path in
  `rag/store.py::upsert_chunks` (`ON CONFLICT DO UPDATE`).

**Indexes**:

- `documents_pkey` (PK on id)
- `documents_source_url_chunk_idx_key` (unique constraint index)
- `idx_documents_embedding_hnsw` (HNSW cosine, pgvector ≥ 0.5.0)
- `idx_documents_wiki_lang` (btree, for language filtering)

**Migration application path pivot**: The plan called for
`apply_migration` via the Supabase MCP. Runtime discovery: the MCP
is configured `read_only=true` in `.mcp.json` (per § 0.7 safety
default), so DDL is rejected. Pivoted to raw `psycopg` executed
against the app's `DATABASE_URL` (session pooler, port 5432,
`postgres.<REF>` role). The DDL is idempotent (`CREATE ... IF NOT
EXISTS`) and can be re-run safely.

**Do NOT** flip the MCP to `read_only=false` just to enable
migrations — that would expose the entire Supabase project to any
tool call the LLM decides to make. Keep the manual `psycopg`
migration path.

---

## 2.4 — pgvector: `Vector()` wrap is REQUIRED for `<=>`, but NOT for INSERT

**Bug discovered at first case #1 run**:

```
UndefinedFunction: operator does not exist: vector <=> double precision[]
```

**Cause**: `register_vector_async` (from § 0.3) lets psycopg infer
the vector type when the target is a known `vector(...)` column —
INSERT worked with a raw `list[float]`. But in a standalone
comparison `embedding <=> %s`, the RHS is untyped; psycopg sends
`list[float]` as PostgreSQL `double precision[]`, and Postgres cannot
match that against the `<=>` operator overload (which is
`vector <=> vector`).

**Fix** (in `src/matchday_agent/rag/store.py::similar`):

```python
from pgvector import Vector

vec = Vector(query_vec)  # explicit wrap
await cur.execute(
    "SELECT ... embedding <=> %s AS distance "
    "... ORDER BY embedding <=> %s LIMIT %s",
    (vec, vec, k),
)
```

**Rule of thumb for Phase 3+**: any raw vector expression outside a
direct column INSERT MUST wrap the operand with `Vector()`. INSERT
into a `vector(N)` column does NOT need the wrap (Postgres knows the
target type). This asymmetry is easy to miss.

---

## 2.5 — RAG tool wiring: compose at CLI, keep graph generic

`src/matchday_agent/graph.py` accepts `tools: list[BaseTool]` as an
opaque parameter — it does not know about MCP tools vs RAG tools vs
future tools. Composition happens in `src/matchday_agent/cli.py`:

```python
mcp_tools = await stack.enter_async_context(matchday_mcp_tools())
tools = [*mcp_tools, search_football_context]
agent = build_agent(model=model, tools=tools, checkpointer=checkpointer)
```

This keeps `graph.py` reusable for tool-set variations without
editing the graph builder — e.g. Phase 4 eval runs that swap tools,
per-user gating, or a lite tool-set for cheaper inference.

**For Phase 3** (FastAPI `lifespan`): apply the same append pattern
in the `lifespan` handler. Do NOT push the composition into
`graph.py`.
