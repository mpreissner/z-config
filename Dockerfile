# ── Stage 1: Node / Vite build ──────────────────────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --prefer-offline

COPY web/ ./
# Vite config already sets outDir = "../api/static"
RUN npm run build


# ── Stage 2: Python runtime ──────────────────────────────────────────────────
# Pin to a digest for production builds — Python minor version upgrades are
# intentional image rebuilds, not automatic. Example:
#   FROM python:3.12-slim@sha256:<digest> AS runtime
FROM python:3.12-slim AS runtime

WORKDIR /app

# System deps:
# - git: needed by pip for plugin installs from GitHub URLs (pip install git+https://...)
# - libxml2-dev / libxslt-dev / libxmlsec1-dev / pkg-config: required by xmlsec1 (SAML auth)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libxml2-dev \
    libxslt-dev \
    libxmlsec1-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (api extras required)
COPY pyproject.toml requirements.txt* ./
RUN pip install --no-cache-dir ".[api]"

# Copy application source
COPY api/      ./api/
COPY cli/      ./cli/
COPY db/       ./db/
COPY lib/      ./lib/
COPY services/ ./services/

# Copy compiled frontend from stage 1
COPY --from=frontend-build /build/api/static ./api/static

# Data directories — real content comes from mounted volumes
RUN mkdir -p /data/db /data/plugins

# Non-root user for defence-in-depth
RUN useradd -r -u 1001 -g root zsconfig && chown -R zsconfig:root /app /data
USER zsconfig

ENV ZS_CONTAINER_MODE=1
ENV ZSCALER_DB_PATH=/data/db/zscaler.db
ENV ZS_PLUGIN_DIR=/data/plugins
ENV PYTHONUSERBASE=/data/plugins
ENV PYTHONUNBUFFERED=1
# Point HOME at the persistent DB volume so the Fernet key file
# (~/.config/zs-config/secret.key) survives container restarts and image upgrades.
ENV HOME=/data/db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
