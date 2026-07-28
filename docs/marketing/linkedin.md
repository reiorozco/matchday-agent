# LinkedIn assets — matchday stack v1

Copy-paste-ready drafts for the LinkedIn Featured card + build-in-public
posts announcing the matchday agentic stack (MCP + Agent + Web).

Both **Spanish** and **English** variants. Pick per audience.

Post history / cross-refs (per spec 004 Phase 7):

- **Featured card**: replaces the existing "matchday" Featured item with
  a stack-oriented one (MCP + Agent + Web) pointing to the agent repo.
- **Post 1**: retrospective on Phase 2 (RAG shipped) — deeply technical.
- **Post 2**: milestone on Phase 5-6 (live URL + public repo + handoff
  issue) — shipping-focused, ends with a working curl.

---

## LinkedIn Featured card

### Description field — Spanish (~200 chars)

> Agente football-analyst end-to-end en Python: LangGraph + Wikipedia RAG sobre Supabase pgvector + observabilidad LangSmith + streaming SSE. Orquesta matchday-mcp (npm) y responde en el idioma del usuario (default: inglés). Deploy en Fly.io.

### Description field — English (~200 chars)

> End-to-end football-analyst agent in Python: LangGraph + Wikipedia RAG on Supabase pgvector + LangSmith tracing + SSE streaming. Orchestrates matchday-mcp (npm), responds in the user's language (default: English). Deployed on Fly.io.

### URL

`https://github.com/reiorozco/matchday-agent`

### Alternative Featured URL (live demo)

`https://matchday-agent.fly.dev`

Description (ES): `Agente en vivo. POST /chat/stream devuelve tokens + tool calls por SSE en tiempo real. Try: "Cómo llega Real Madrid al clásico" con historia + stats.`
Description (EN): `Live agent. POST /chat/stream returns SSE tokens + tool calls in real time. Try: "How is Real Madrid arriving to el clásico" with history + stats.`

---

## Post 1 — "Phase 2: RAG shipped" (retrospective)

### Spanish

```
De 0 a 2400 chunks de Wikipedia en Supabase pgvector.

Cerré Phase 2 de matchday-agent (el agente que estoy construyendo sobre
matchday-mcp): RAG multilingual funcionando.

El stack:

- Ingest: Wikipedia-API 0.15 sobre 68 URLs (20 clubes de LaLiga + 20 de Premier
  League + 10 finales/derbies famosos), en ES + EN
- Embedder: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  (384d, Apache-2.0) via fastembed — ONNX local, sin API calls ni rate limits
- Chunker: RecursiveCharacterTextSplitter.from_tiktoken_encoder (480 tokens,
  overlap 64) — NO el default por caracteres
- Store: Supabase pgvector con index HNSW cosine + register_vector_async

El agente ahora responde "¿cómo llega el Real Madrid al clásico?" mezclando:

- Standings actuales via MCP tool (get_standings)
- Últimos partidos via MCP tool (get_team_matches)
- Historia del clásico via RAG tool (search_football_context sobre Wikipedia)

Cada dato con su fuente inline:
"(fuente: get_standings)", "(fuente: search_football_context)".

Un detalle que dolió: el operador <=> de pgvector NO acepta list[float]
en queries sueltas — solo en INSERTs a columna vector tipada. Fix: envolver
con pgvector.Vector(...) en todo query. 30 min de "¿por qué mi query truena
y mi insert funciona?"

Repo: https://github.com/reiorozco/matchday-agent

#RAG #pgvector #Wikipedia #LangGraph #Python #Supabase
```

### English

```
From 0 to 2400 Wikipedia chunks on Supabase pgvector.

Closed Phase 2 of matchday-agent (the agent I'm building on top of
matchday-mcp): multilingual RAG working.

The stack:

- Ingest: Wikipedia-API 0.15 across 68 URLs (20 LaLiga clubs + 20 Premier League
  clubs + 10 famous finals/derbies), in ES + EN
- Embedder: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  (384d, Apache-2.0) via fastembed — local ONNX, no API calls, no rate limits
- Chunker: RecursiveCharacterTextSplitter.from_tiktoken_encoder (480 tokens,
  overlap 64) — NOT the default character-based one
- Store: Supabase pgvector with HNSW cosine index + register_vector_async

The agent now answers "how is Real Madrid arriving to el clásico?" by
combining:

- Current standings via MCP tool (get_standings)
- Recent form via MCP tool (get_team_matches)
- El clásico history via RAG tool (search_football_context on Wikipedia)

Each fact cites its source inline:
"(source: get_standings)", "(source: search_football_context)".

One detail that hurt: pgvector's <=> operator does NOT accept list[float]
in standalone queries — only in INSERTs to typed vector columns. Fix: wrap
with pgvector.Vector(...) in every query expression. 30 min of "why does
my query throw and my insert work?"

Repo: https://github.com/reiorozco/matchday-agent

#RAG #pgvector #Wikipedia #LangGraph #Python #Supabase
```

---

## Post 2 — "Phase 5-6: v1 shipped, live on Fly.io" (milestone)

### Spanish

```
matchday-agent v1 shipped — live en Fly.io.

https://matchday-agent.fly.dev

Lo que podés hacer AHORA desde tu terminal:

    UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
    curl -N -X POST https://matchday-agent.fly.dev/chat/stream \
      -H 'Content-Type: application/json' \
      -H "X-Session-Id: $UUID" \
      -d '{"message":"Compará Real Madrid vs Barcelona esta temporada"}'

Vas a ver 3 tool_calls en paralelo (compare_teams + find_team ×2), luego
tokens en español streaming, luego un final. En ~2.5 segundos con la máquina
warm; ~20s cold-start desde stopped.

El deploy no fue trivial:

- 4 iteraciones del Dockerfile: uv sync como root arruinó los permisos de
  .venv, uv run re-syncing on container start, --frozen faltando, y un
  --no-install-project que necesitaba estar antes del COPY para preservar
  layer caching
- Cold start de 20.79s (2.5x el target de spec — Firecracker boot +
  Python imports + lifespan setup con Postgres + npx matchday-mcp subprocess)
- Groq TPD (100k tokens/día) encontrado en producción DE NUEVO — la reality
  del free-tier a portfolio scale
- Auto-stop de Fly funcionando después de ~4 min idle. Cost-safe scale-to-zero
  verificado (verificado por cold-start-from-stopped on primera request)

Repo público con README de 200 líneas + docs/decisions.md de 1900+ líneas
explicando el "por qué" de cada decisión (incluyendo los 4 fixes del
Dockerfile):

https://github.com/reiorozco/matchday-agent

Y para el frontend (Svelte 5 consuming el SSE contract), hay un GitHub
issue detallado con contract table + sample code + DoD checklist:

https://github.com/reiorozco/matchday-mcp-web/issues/1

Aprendí más de despliegue en Phase 5 que del agente en sí. La MCP subprocess
dentro de un container Fly.io con non-root user + venv ownership + npx cache
warmup es un pequeño reto que no aparece en tutorials.

#LangGraph #FastAPI #SSE #Fly #DevOps #LLM #Python
```

### English

```
matchday-agent v1 shipped — live on Fly.io.

https://matchday-agent.fly.dev

What you can do RIGHT NOW from your terminal:

    UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
    curl -N -X POST https://matchday-agent.fly.dev/chat/stream \
      -H 'Content-Type: application/json' \
      -H "X-Session-Id: $UUID" \
      -d '{"message":"Compare Real Madrid vs Barcelona this season"}'

You'll see 3 parallel tool_calls (compare_teams + find_team ×2), then
streaming English tokens, then a final. In ~2.5 seconds with a warm
machine; ~20s cold-start from stopped. Ask in Spanish/Portuguese/French
and the agent mirrors your language — no forcing.

The deploy was not trivial:

- 4 Dockerfile iterations: uv sync as root wrecked .venv permissions,
  uv run re-syncing on container start, missing --frozen, and a
  --no-install-project that needed to sit before COPY to preserve
  layer caching
- 20.79s cold start (2.5x the spec target — Firecracker boot +
  Python imports + lifespan setup with Postgres + npx matchday-mcp subprocess)
- Groq's 100k TPD daily cap hit in production AGAIN — free-tier reality
  at portfolio scale
- Fly's auto-stop firing after ~4 min idle. Cost-safe scale-to-zero
  verified (via cold-start-from-stopped on the initial request)

Public repo with a 200-line README + 1900+ line docs/decisions.md
explaining the "why" of every decision (including the 4 Dockerfile fixes):

https://github.com/reiorozco/matchday-agent

For the Svelte 5 frontend consuming the SSE contract, there's a detailed
GitHub issue with the contract table + sample code + DoD checklist:

https://github.com/reiorozco/matchday-mcp-web/issues/1

Learned more from Phase 5 deployment than from the agent itself. Running
an MCP subprocess inside a Fly.io container with non-root user + venv
ownership + npx cache warmup is a small challenge that doesn't show up
in tutorials.

#LangGraph #FastAPI #SSE #Fly #DevOps #LLM #Python
```

---

## Profile README update (applied 2026-07-27)

Applied at `https://github.com/reiorozco/reiorozco` in the same
Phase 7 commit. Three changes:

1. **Featured Projects table** — inserted `matchday-agent` as the new
   top row (highlights the LangGraph + RAG + SSE + Fly stack that
   matchday-mcp powers).
2. **`matchday-mcp` row description** — small tweak to reference
   `matchday-agent` as the consumer of its 6 tools.
3. **Currently Learning → AI Engineering bullet** — expanded to
   include "LangGraph agents with RAG and observability", pointing
   to the new repo.

Rationale: preserves the existing card style (emoji headers,
`skillicons.dev` badges, GitHub Stats block) while surfacing the
new v1-shipped work at the top. Recruiters scanning the profile
see the newest, most ambitious project first.

---

## Memory files (user-owned, not touched)

Per spec 004 Phase 7 checklist, the user's private memory files
`marca-profesional-2026` + `github-audit-2026` should be updated
to reflect Phase 5-6 shipped state + Phase 7 LinkedIn assets. Those
files live in the user's personal memory system (outside this repo)
— left for the user to sync manually.
