# Multi-stage: build the dashboard with node, then serve it from the Python
# API. The result is one self-contained image that needs no second service —
# main.py mounts dashboard/dist when it exists.

# --- stage 1: dashboard ----------------------------------------------------
FROM node:20-alpine AS dashboard

WORKDIR /dash
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
# Same-origin: the API serves these files, so no build-time API URL is needed.
RUN npm run build


# --- stage 2: runtime ------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git is a runtime dependency: the agent clones and reads the watched repo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only what the install needs first, so dependency layers cache across
# source edits.
COPY pyproject.toml README.md ./
COPY docsentry/ ./docsentry/
RUN pip install .

COPY --from=dashboard /dash/dist ./dashboard/dist

# The agent clones into here; keep it writable for a non-root user.
RUN useradd --create-home --uid 1000 sentry \
    && mkdir -p /app/.docsentry \
    && chown -R sentry:sentry /app
USER sentry

# git refuses to operate on a repo it thinks belongs to someone else.
RUN git config --global --add safe.directory '*'

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# Shell form so $PORT (Render, HF Spaces, Fly) is expanded; falls back to 8000.
CMD uvicorn docsentry.main:app --host 0.0.0.0 --port ${PORT:-8000}
