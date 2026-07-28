# Multi-stage build: Python 3.12 base + Node 20 runtime for `npx matchday-mcp`.
# Validated in Phase 0 (docs/decisions.md § 0.2 and § 0.6). ~180 MB final image.

# ── Stage 1: Node runtime, source of the binaries we copy over. ──────────────
FROM node:20-slim AS node-base

# ── Stage 2: Python app + copied Node binaries. ──────────────────────────────
FROM python:3.12-slim

# Copy Node + node_modules from node-base; symlink npm/npx into /usr/local/bin.
# Only ~90 MB added vs. `apt-get install nodejs npm` (~500 MB) or NodeSource.
COPY --from=node-base /usr/local/bin/node /usr/local/bin/node
COPY --from=node-base /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install uv 0.9.20 globally (invoked as appuser after the USER switch below).
RUN pip install --no-cache-dir uv==0.9.20

# Non-root user + WORKDIR owned by it BEFORE running `uv sync` — otherwise
# .venv/ ends up owned by root and any runtime attempt to touch it (e.g.
# `uv run` re-syncing project scripts) hits "Permission denied" and crashes
# the container. Phase 5 debug: fixed after the initial deploy loop-crashed
# 10x on `bin/evals` permission errors — see docs/decisions.md § 5.x.
RUN useradd -m -u 1000 appuser && mkdir -p /app && chown appuser:appuser /app
WORKDIR /app
USER appuser

# Put the venv on PATH so subsequent RUNs (and CMD) can call the installed
# entry points directly, bypassing `uv run` — no re-sync attempt at start.
ENV PATH="/app/.venv/bin:${PATH}"

# Two-step uv sync for optimal layer caching. `--frozen` forces uv to use the
# committed uv.lock verbatim and fails the build if it drifts from
# pyproject.toml — Phase 5 guarantee for reproducible deploys.
#
# Step 1: install third-party dependencies ONLY. `--no-install-project` skips
# the local `matchday-agent` package (which needs src/ to exist). This layer
# is cached across all pure-code changes → most rebuilds skip re-installing
# the ~90 pinned deps (~2 min saved per iteration).
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# Pre-bake the fastembed RAG embedder model into the image so Fly cold
# starts don't re-download ~220 MB of weights on the first RAG query.
# Cached as its own layer — invalidated only when the embedder model
# changes (rare). See decisions.md § 8.10 (audit response for the
# original 2.24 GB OOM crash on the 512 MB VM).
RUN /app/.venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# App source. `.dockerignore` excludes .env / .venv / .git / caches / docs —
# see that file for the full exclusion list.
COPY --chown=appuser:appuser . .

# Step 2: install the local `matchday-agent` package now that src/ is present.
# Phase 5 debug: the first deploy had this step missing, so uvicorn crashed
# with `ModuleNotFoundError: No module named 'matchday_agent'` on start.
RUN uv sync --no-dev --frozen

# Fail-fast sanity: matchday-mcp must be resolvable at build time. Running as
# appuser populates /home/appuser/.npm so the runtime MCP subprocess spawned
# by mcp_tools.py hits a warm cache instead of the ~500 ms npm fetch on the
# first request.
RUN npx -y matchday-mcp --version || (echo "npx matchday-mcp failed" && exit 1)

EXPOSE 8080

# Minimal in-container health probe (uvicorn liveness).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health', timeout=3).status == 200 else 1)" \
  || exit 1

# Direct invocation via absolute path — NOT `uv run uvicorn ...`. `uv run`
# triggers a project re-sync on every container start (rebuilding the local
# wheel + reinstalling entry points), which fails on read-only .venv/ layers
# and adds seconds to cold start even when it succeeds.
CMD ["/app/.venv/bin/uvicorn", "matchday_agent.app:app", "--host", "0.0.0.0", "--port", "8080"]
