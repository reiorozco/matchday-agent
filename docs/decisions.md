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
