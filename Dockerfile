# Multi-stage build: Python 3.12 base + Node 20 runtime for `npx matchday-mcp`.
# Validated in Phase 0 (docs/decisions.md § 0.2 and § 0.6). ~330 MB final image.

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

# Install uv 0.9.20 for reproducible Python installs.
RUN pip install --no-cache-dir uv==0.9.20

# Non-root user (Fly.io best practice).
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Install Python deps first (best layer caching).
# Phase 0: run `uv lock` locally once so uv.lock exists, then switch to --frozen.
COPY --chown=appuser:appuser pyproject.toml uv.lock* ./
RUN uv sync --no-dev

# App source.
COPY --chown=appuser:appuser . .

# Fail-fast sanity: matchday-mcp must be resolvable at build time.
# Note: this runs `npm install` under the hood the first time; subsequent
#   invocations at runtime hit the local cache and are ~250 ms.
RUN npx -y matchday-mcp --version || (echo "npx matchday-mcp failed" && exit 1)

USER appuser
EXPOSE 8080

# Minimal in-container health probe (uvicorn liveness).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health', timeout=3).status == 200 else 1)" \
  || exit 1

CMD ["uv", "run", "uvicorn", "matchday_agent.app:app", "--host", "0.0.0.0", "--port", "8080"]
