# matchday-agent — HTTP + SSE API contract

Public contract for consumers of the matchday-agent HTTP surface — the
frontend `matchday-mcp-web.vercel.app`, evaluation runners, and integration
tests. Frozen in Phase 3 (2026-07-26); breaking changes require bumping the
`version` field on `GET /` (currently `0.1.0`; no `/v1/` URL prefix).

Implementation: [`src/matchday_agent/app.py`](../src/matchday_agent/app.py).

## Endpoints

| Method | Path            | Purpose                                        | Rate limit         |
|--------|-----------------|------------------------------------------------|--------------------|
| GET    | `/`             | App metadata (about-page)                      | unlimited          |
| GET    | `/health`       | Wake probe (Fly.io + external monitors)        | unlimited          |
| GET    | `/openapi.json` | Auto-generated OpenAPI schema (FastAPI)        | unlimited          |
| POST   | `/chat`         | Non-streaming JSON in/out (evals + tests)      | 20 req/min per IP  |
| POST   | `/chat/stream`  | SSE — primary path for the web                 | 20 req/min per IP  |

## `GET /`

Returns app metadata (used by the web's "about" page).

```json
{
  "name": "matchday-agent",
  "version": "0.1.0",
  "model": "groq:llama-3.3-70b-versatile",
  "tools": [
    "get_standings", "get_matches", "get_top_scorers",
    "find_team", "get_team_matches", "compare_teams",
    "search_football_context"
  ]
}
```

## `GET /health`

Wake probe for Fly.io. 200 as long as the process is alive.

```json
{ "ok": true, "version": "0.1.0" }
```

## `POST /chat` and `POST /chat/stream` — common request

Headers:

| Header          | Value                                                                 |
|-----------------|-----------------------------------------------------------------------|
| `Content-Type`  | `application/json` (required)                                         |
| `X-Session-Id`  | UUID v4 (required). Used verbatim as LangGraph `thread_id`. Invalid → 400. |
| `Accept`        | `application/json` (`/chat`) or `text/event-stream` (`/chat/stream`)  |

Body:

```json
{ "message": "¿Cómo va el Real Madrid?" }
```

Constraints: `1 <= len(message) <= 4000`.

## `POST /chat` — non-streaming response

```json
{
  "message": "El Real Madrid marcha 2° en LaLiga con 86 puntos (fuente: get_standings).",
  "session_id": "<echoed X-Session-Id>",
  "sources": []
}
```

**v1 note — `sources: []`**: always empty in v1. Phase 4 will populate it
with structured cited-source entries `[{"kind": "tool" | "rag", "tool": "...", "url": "..."}]`
from tool calls and RAG hits. Until then, the frontend can inline-parse the
`(fuente: X)` markers embedded in `message`.

**Reserved for Phase 4+**:
- `usage: {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}` —
  LangChain's Groq/Gemini adapters don't currently surface token counts on
  `ainvoke`; Phase 4 will hook `on_llm_end` events to extract them.

**Errors**:

| Status | Body                                                                    |
|--------|-------------------------------------------------------------------------|
| 400    | `{ "detail": "X-Session-Id header is required (UUID v4)." }`            |
| 422    | `{ "detail": [ { "loc": [...], "msg": "..." } ] }` (Pydantic validation)|
| 429    | `{ "error": "Rate limit exceeded: 20 per 1 minute" }`                   |

## `POST /chat/stream` — SSE event contract

Response headers (auto-set by `sse-starlette`; required for Fly.io + Vercel
edge no-buffering):

```
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
Transfer-Encoding: chunked
```

Event kinds (each `event:` line is followed by a `data:` line whose payload
is JSON):

### `event: token`

One LLM chunk. Concatenate `text` in order to render the live answer.

```
event: token
data: {"text": "El "}

event: token
data: {"text": "Real "}
```

### `event: tool_call`

Emitted when the agent invokes a tool. `id` is the LangGraph `run_id` and is
echoed by the matching `tool_result`.

```
event: tool_call
data: {"id": "run_01H...", "tool": "get_standings", "input": {"competition": "PD"}}
```

Parallel tool calls arrive as consecutive `tool_call` events (see anchor case
#4 — "cuál liga está más disputada" emits 5 `tool_call` events for the 5
top-league standings).

### `event: tool_result`

Emitted when the tool completes. `summary` is the tool output truncated to
~300 chars.

```
event: tool_result
data: {"id": "run_01H...", "tool": "get_standings", "ok": true, "summary": "..."}
```

**v1 note — `ok`**: always `true`. In v1, tool errors surface via
`event: error` and terminate the stream. Phase 4+ will let `ok=false` signal
recoverable per-tool failures the agent can react to.

### `event: final`

Fires exactly once at end of turn with the full accumulated `message`. After
`final`, the server closes the stream; clients should treat any subsequent
events as noise.

```
event: final
data: {"message": "El Real Madrid ...", "sources": []}
```

Same `sources: []` v1 note as `POST /chat`.

### `event: error`

Fires on any exception. Terminates the stream.

```
event: error
data: {"code": "TypeError", "message": "..."}
```

**v1 note — `code`**: the Python exception class name. Structured codes
(`upstream_llm_timeout`, `rate_limit_exceeded`, ...) paired with
`retry_after` are Phase 4+.

### `event: ping` (RESERVED — not emitted in v1)

Reserved event kind for keeping intermediate proxies alive on long-running
turns. Anchor cases complete under 30s so v1 does not need it. Documented
here so consumers can start ignoring unknown events from day one.

## CORS

Origins whitelisted via `ALLOWED_ORIGINS` env (comma-separated).

- Production: `https://matchday-mcp-web.vercel.app`
- Local dev: also `http://localhost:5173`

Non-listed origins receive the browser's default CORS block (response is
returned without the `Access-Control-Allow-Origin` header). curl and other
non-browser clients are unaffected.

Allowed methods: `GET`, `POST`.
Allowed headers: `Content-Type`, `X-Session-Id`.

## Rate limiting

`slowapi` with the in-memory backend, keyed by client IP.

| Endpoint            | Limit             |
|---------------------|-------------------|
| `GET /`             | unlimited         |
| `GET /health`       | unlimited         |
| `GET /openapi.json` | unlimited         |
| `POST /chat`        | 20 req / min / IP |
| `POST /chat/stream` | 20 req / min / IP |

## Session semantics

- `X-Session-Id` is treated verbatim as the LangGraph `thread_id`.
- State persists across process restarts (Fly.io auto-stop + cold-start)
  because `AsyncPostgresSaver` writes to Supabase Postgres.
- Reusing the same UUID continues a prior conversation; a new UUID starts
  fresh.
- The web client persists one UUID per tab in `localStorage`.

**Security note**: no cross-session read protection in v1 (no auth).
Guessing another client's UUID lets you read their state. Documented
limitation; revisit before opening beyond the demo web.

## Versioning

- v1 is implicit (no `/v1/` URL prefix).
- **Breaking** changes (renamed SSE event kinds, renamed JSON keys, removed
  fields) require introducing `/v2/` alongside `/v1/`.
- **Additive** changes (new optional keys, new event kinds consumers are
  told to ignore) are backward-compatible.

## Local smoke recipe

```bash
uv run --env-file .env uvicorn matchday_agent.app:app --port 8000

curl -s http://127.0.0.1:8000/ | jq
curl -s http://127.0.0.1:8000/health | jq

UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')

curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -H "X-Session-Id: $UUID" \
  -d '{"message":"¿Cómo va el Real Madrid en LaLiga?"}' | jq

curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H 'Content-Type: application/json' \
  -H "X-Session-Id: $UUID" \
  -d '{"message":"¿Cómo va el Real Madrid en LaLiga?"}'
```
