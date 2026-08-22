# Magpie Cloud — production Docker image.
#
# Multi-stage build. Stage 1 (`builder`) installs uv and resolves the
# Python deps into a virtualenv. Stage 2 (`runtime`) is the slim image
# we actually deploy — copies just the venv and the magpie_server
# package. No build tools, no caches.
#
# Build:    docker build -f server/Dockerfile -t magpie-cloud server/
# Run:      docker run --rm -p 8000:8000 \
#               -e OPENROUTER_API_KEY=sk-or-v1-... \
#               -e INVITE_CODES=alice-abc123 \
#               magpie-cloud
# Deploy:   fly deploy   (uses this Dockerfile + server/fly.toml)
#
# Final image size target: ~150 MB. If it grows, audit the deps in
# server/pyproject.toml — torch / qdrant_client / colpali are
# desktop-only and must NOT show up here.

# ---------------------------------------------------------------------------
# Stage 1 — build the venv
# ---------------------------------------------------------------------------

FROM python:3.11-slim AS builder

# uv is the same package manager we use in dev. Pinned for reproducibility.
COPY --from=ghcr.io/astral-sh/uv:0.5.7 /uv /usr/local/bin/uv

WORKDIR /app

# Copy only what's needed to resolve deps. Source code comes in stage 2.
# This way `pip install` step caches as long as pyproject.toml is unchanged.
COPY pyproject.toml ./

# Install into a project-local .venv that we'll copy to the runtime stage.
RUN uv venv /app/.venv \
 && UV_PROJECT_ENVIRONMENT=/app/.venv uv pip install --no-cache-dir -e .

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------

FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy the resolved venv from the builder. No build tools land here.
COPY --from=builder /app/.venv /app/.venv

# Now the source. Doing it last means code edits don't bust the dep cache.
COPY pyproject.toml ./
COPY magpie_server ./magpie_server

# Run as a non-root user. fly.io / Render don't strictly require this
# but it's a basic hardening move for any container in 2026.
RUN groupadd --system magpie && useradd --system --gid magpie magpie \
 && chown -R magpie:magpie /app
USER magpie

# Network config. Bind to 0.0.0.0 so the container's port 8000 is
# reachable from outside; fly.io's proxy will TLS-terminate in front.
ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

# Use the venv's python directly (no `uv run` overhead at startup).
ENV PATH="/app/.venv/bin:${PATH}"

# Healthcheck for fly.io / Docker. Hits the unauthenticated /health
# endpoint and expects 200. Liveness only — readiness depends on env
# vars (OPENROUTER_API_KEY etc.) which fly.io secrets injects.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "magpie_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
