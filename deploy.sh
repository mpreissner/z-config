#!/usr/bin/env bash
# deploy.sh — Pull, build, and deploy zs-config on a Docker host.
#
# Works in two modes:
#   1. Standalone (fresh machine) — run the script directly; it will clone
#      the repo into ./zs-config next to the script, then deploy from there.
#   2. Inside the repo — run from an existing clone; it will pull and redeploy.
#
# Usage:
#   ./deploy.sh [branch]
#
# Single-command deploy on a fresh machine:
#   curl -fsSL https://raw.githubusercontent.com/mpreissner/zs-config/main/deploy.sh | bash

set -euo pipefail

REPO_URL="https://github.com/mpreissner/zs-config.git"
BRANCH="${1:-main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Preflight ─────────────────────────────────────────────────────────────────

if ! command -v docker &>/dev/null; then
    echo "ERROR: docker is not installed or not in PATH." >&2
    exit 1
fi

if ! docker compose version &>/dev/null; then
    echo "ERROR: docker compose (v2) is required." >&2
    exit 1
fi

# ── Clone if not already inside the repo ─────────────────────────────────────

if [[ -f "$SCRIPT_DIR/.git/config" ]] || git -C "$SCRIPT_DIR" rev-parse --git-dir &>/dev/null; then
    REPO_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
    cd "$REPO_DIR"
    echo "Fetching latest code..."
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    REPO_DIR="$SCRIPT_DIR/zs-config"
    if [[ -d "$REPO_DIR" ]]; then
        echo "Found existing clone at $REPO_DIR, pulling latest..."
        cd "$REPO_DIR"
        git fetch origin
        git checkout "$BRANCH"
        git pull origin "$BRANCH"
    else
        echo "Cloning $REPO_URL into $REPO_DIR..."
        git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
        cd "$REPO_DIR"
    fi
fi

# ── Ensure JWT_SECRET is set ──────────────────────────────────────────────────

if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
fi

if [[ -z "${JWT_SECRET:-}" ]]; then
    if ! command -v openssl &>/dev/null; then
        echo "ERROR: JWT_SECRET is not set and openssl is not available to generate one." >&2
        echo "Set JWT_SECRET in $REPO_DIR/.env before running this script." >&2
        exit 1
    fi
    JWT_SECRET="$(openssl rand -hex 32)"
    echo "JWT_SECRET=$JWT_SECRET" >> "$REPO_DIR/.env"
    echo "Generated JWT_SECRET and saved to $REPO_DIR/.env — keep this file safe."
fi

# ── Ensure persistent Docker volumes exist ────────────────────────────────────

for vol in zs-config_zs-db zs-config_zs-plugins; do
    if ! docker volume inspect "$vol" &>/dev/null; then
        echo "Creating Docker volume: $vol"
        docker volume create "$vol"
    fi
done

# ── Inject host trust store ───────────────────────────────────────────────────
# Exports trusted root certs into docker/ca-bundle.pem so the image includes
# any corporate SSL-inspection CAs present on this machine.  Cleared on exit
# so the file is never committed with real cert content.

BUNDLE="$REPO_DIR/docker/ca-bundle.pem"
cleanup_bundle() { : > "$BUNDLE"; }
trap cleanup_bundle EXIT

: > "$BUNDLE"
if [[ "$(uname)" == "Darwin" ]]; then
    echo "Exporting macOS trust store → docker/ca-bundle.pem"
    security find-certificate -a -p \
        /System/Library/Keychains/SystemRootCertificates.keychain >> "$BUNDLE"
    security find-certificate -a -p \
        /Library/Keychains/System.keychain >> "$BUNDLE" 2>/dev/null || true
    security find-certificate -a -p \
        "$HOME/Library/Keychains/login.keychain-db" >> "$BUNDLE" 2>/dev/null || true
else
    # On Linux, copy the host system store (includes any corp CAs installed there)
    [[ -f /etc/ssl/certs/ca-certificates.crt ]] && \
        cp /etc/ssl/certs/ca-certificates.crt "$BUNDLE" || true
fi

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
