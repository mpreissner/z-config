#!/usr/bin/env bash
# deploy.sh — Pull, build, and deploy zs-config on a Docker host.
#
# Usage:
#   ./deploy.sh [branch]
#
# The branch defaults to "feature/web-frontend". Set JWT_SECRET in the
# environment or in a .env file before running if this is a first-time deploy.
#
# First-time setup:
#   export JWT_SECRET="$(openssl rand -hex 32)"   # save this somewhere safe
#   ./deploy.sh
#
# Subsequent deploys (just pull and rebuild):
#   ./deploy.sh

set -euo pipefail

BRANCH="${1:-feature/web-frontend}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Preflight ─────────────────────────────────────────────────────────────────

if ! command -v docker &>/dev/null; then
    echo "ERROR: docker is not installed or not in PATH." >&2
    exit 1
fi

if ! docker compose version &>/dev/null; then
    echo "ERROR: docker compose (v2) is required." >&2
    exit 1
fi

# ── Ensure JWT_SECRET is set ──────────────────────────────────────────────────

if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
fi

if [[ -z "${JWT_SECRET:-}" ]]; then
    echo "ERROR: JWT_SECRET is not set."
    echo ""
    echo "Generate one and add it to .env:"
    echo "  echo \"JWT_SECRET=\$(openssl rand -hex 32)\" >> .env"
    echo ""
    echo "Or export it before running this script:"
    echo "  export JWT_SECRET=\"\$(openssl rand -hex 32)\""
    exit 1
fi

# ── Ensure persistent Docker volumes exist ────────────────────────────────────

for vol in zs-config_zs-db zs-config_zs-plugins; do
    if ! docker volume inspect "$vol" &>/dev/null; then
        echo "Creating Docker volume: $vol"
        docker volume create "$vol"
    fi
done

# ── Pull latest code ──────────────────────────────────────────────────────────

cd "$REPO_DIR"

echo "Fetching from origin..."
git fetch origin

echo "Checking out branch: $BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"

# ── Build ─────────────────────────────────────────────────────────────────────

echo "Building image..."
docker compose build

# ── Deploy ────────────────────────────────────────────────────────────────────

echo "Stopping existing container..."
docker compose down

echo "Starting container..."
docker compose up -d

# ── Health check ──────────────────────────────────────────────────────────────

echo "Waiting for health check..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/health &>/dev/null; then
        echo ""
        echo "zs-config is running at http://localhost:8000"
        echo ""
        docker compose logs --tail=5
        exit 0
    fi
    printf "."
    sleep 1
done

echo ""
echo "WARNING: Health check did not pass within 15 seconds. Check logs:"
echo "  docker compose logs"
exit 1
