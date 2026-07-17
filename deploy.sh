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
DC_BACKUP=""

NON_INTERACTIVE=0
for arg in "$@"; do
    case "$arg" in
        --non-interactive) NON_INTERACTIVE=1 ;;
    esac
done

# ── Preflight ─────────────────────────────────────────────────────────────────

_install_pkg() {
    local pkg="$1"
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y "$pkg"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "$pkg"
    elif command -v yum &>/dev/null; then
        sudo yum install -y "$pkg"
    elif command -v brew &>/dev/null; then
        brew install "$pkg"
    else
        echo "ERROR: Cannot install $pkg — no supported package manager found (apt/dnf/yum/brew)." >&2
        exit 1
    fi
}

if ! command -v git &>/dev/null; then
    echo "git not found. Installing..."
    _install_pkg git
fi

if ! command -v docker &>/dev/null; then
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "ERROR: Docker Desktop is not running or not installed." >&2
        echo "Install from https://docs.docker.com/desktop/install/mac-install/ and start it, then re-run." >&2
        exit 1
    fi
    echo "docker not found. Installing via get.docker.com..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER" 2>/dev/null || true
    sudo systemctl enable --now docker 2>/dev/null || true
fi

if ! docker compose version &>/dev/null; then
    echo "ERROR: docker compose (v2) is required. Install Docker Engine 20.10+ or add the Compose plugin." >&2
    exit 1
fi

# ── docker-compose.yml diff check ────────────────────────────────────────────
# If docker-compose.yml differs from upstream, show the diff and ask the user
# whether to use the upstream version or preserve their local one.

_compose_diff() {
    local branch="$1"
    local dc_file="$REPO_DIR/docker-compose.yml"
    [[ -f "$dc_file" ]] || return 0

    local tmp_remote
    tmp_remote="$(mktemp)"
    git show "origin/$branch:docker-compose.yml" > "$tmp_remote" 2>/dev/null \
        || { rm -f "$tmp_remote"; return 0; }

    if diff -q "$dc_file" "$tmp_remote" > /dev/null 2>&1; then
        rm -f "$tmp_remote"
        return 0
    fi

    echo ""
    echo "docker-compose.yml differs from upstream (origin/$branch):"
    echo "────────────────────────────────────────────────────────────"
    git diff --no-index \
        --src-prefix="local/" --dst-prefix="upstream/" \
        "$dc_file" "$tmp_remote" || true
    echo "────────────────────────────────────────────────────────────"
    echo ""
    rm -f "$tmp_remote"

    if [[ -t 0 ]] && [[ "$NON_INTERACTIVE" -eq 0 ]]; then
        echo "  [1] Use upstream version (recommended)"
        echo "  [2] Keep my local version"
        read -r -p "Choice [1/2, default 1]: " _dc_choice
        if [[ "${_dc_choice:-1}" == "2" ]]; then
            DC_BACKUP="$(mktemp)"
            mv "$dc_file" "$DC_BACKUP"
            echo "Local docker-compose.yml saved; will be restored after pull."
        fi
    else
        echo "Non-interactive — using upstream docker-compose.yml."
    fi
    echo ""
}

_restore_compose() {
    if [[ -n "$DC_BACKUP" ]]; then
        cp "$DC_BACKUP" "$REPO_DIR/docker-compose.yml"
        rm -f "$DC_BACKUP"
        DC_BACKUP=""
        echo "Restored local docker-compose.yml."
    fi
}

# ── Clone if not already inside the repo ─────────────────────────────────────

if [[ -f "$SCRIPT_DIR/.git/config" ]] || git -C "$SCRIPT_DIR" rev-parse --git-dir &>/dev/null; then
    REPO_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
    cd "$REPO_DIR"
    echo "Fetching latest code..."
    git fetch origin
    _compose_diff "$BRANCH"
    git checkout "$BRANCH"
    git reset --hard "origin/$BRANCH"
    _restore_compose
else
    REPO_DIR="$SCRIPT_DIR/zs-config"
    if [[ -d "$REPO_DIR" ]]; then
        echo "Found existing clone at $REPO_DIR, pulling latest..."
        cd "$REPO_DIR"
        git fetch origin
        _compose_diff "$BRANCH"
        git checkout "$BRANCH"
        git reset --hard "origin/$BRANCH"
        _restore_compose
    else
        echo "Cloning $REPO_URL into $REPO_DIR..."
        git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
        cd "$REPO_DIR"
    fi
fi

# ── Ensure JWT_SECRET is set ──────────────────────────────────────────────────

_existing_install=0
if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
    [[ -n "${JWT_SECRET:-}" ]] && _existing_install=1
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

# ── Network binding ───────────────────────────────────────────────────────────
# BIND_ADDR controls which interface ports 8000/8443 bind to.
# 127.0.0.1 = localhost-only (default, safe for single-user machines)
# 0.0.0.0   = all interfaces (required for server/remote access)

if [[ -z "${BIND_ADDR:-}" ]]; then
    if [[ "$_existing_install" -eq 1 ]]; then
        BIND_ADDR="127.0.0.1"
        echo "BIND_ADDR=${BIND_ADDR}" >> "$REPO_DIR/.env"
        echo "Re-deploy: defaulting network binding to localhost — change BIND_ADDR in .env if needed."
    elif [[ "$NON_INTERACTIVE" -eq 1 ]]; then
        BIND_ADDR="0.0.0.0"
        echo "Non-interactive — network binding set to ${BIND_ADDR}."
    elif [[ -t 0 ]]; then
        echo ""
        echo "Network binding:"
        echo "  [1] Localhost only — 127.0.0.1 (default, single machine)"
        echo "  [2] All interfaces — 0.0.0.0   (server / remote access)"
        read -r -p "Choice [1/2, default 1]: " _bind_choice
        case "${_bind_choice:-1}" in
            2) BIND_ADDR="0.0.0.0" ;;
            *) BIND_ADDR="127.0.0.1" ;;
        esac
    else
        echo "Non-interactive — defaulting to localhost-only binding (127.0.0.1)."
        BIND_ADDR="127.0.0.1"
    fi
    if [[ "$_existing_install" -eq 0 ]]; then
        echo "BIND_ADDR=${BIND_ADDR}" >> "$REPO_DIR/.env"
        echo "Network binding set to ${BIND_ADDR} — saved to .env."
        echo ""
    fi
fi

# ── SSL certificate (optional) ────────────────────────────────────────────────
# If ZS_SSL_DOMAIN is already set (from .env or environment), skip prompting.

if [[ -z "${ZS_SSL_DOMAIN:-}" ]] && [[ "$_existing_install" -eq 0 ]] && [[ -t 0 ]] && [[ "$NON_INTERACTIVE" -eq 0 ]]; then
    echo ""
    echo "SSL certificate (optional):"
    echo "  Skip to use HTTP on port 8000, or provide a cert to enable HTTPS on port 8443."
    read -r -p "Configure SSL now? [y/N]: " _ssl_choice
    if [[ "${_ssl_choice:-N}" =~ ^[Yy]$ ]]; then
        read -r -p "Domain (CN/SAN on the cert, e.g. myapp.company.com): " ZS_SSL_DOMAIN
        read -r -p "Path to certificate file (PEM — leaf + CA chain): " _cert_src
        read -r -p "Path to private key file (PEM): " _key_src

        if [[ ! -f "$_cert_src" ]]; then
            echo "ERROR: Certificate file not found: $_cert_src" >&2
            exit 1
        fi
        if [[ ! -f "$_key_src" ]]; then
            echo "ERROR: Key file not found: $_key_src" >&2
            exit 1
        fi

        mkdir -p "$REPO_DIR/certs"
        cp "$_cert_src" "$REPO_DIR/certs/cert.pem"
        cp "$_key_src"  "$REPO_DIR/certs/key.pem"
        chmod 600 "$REPO_DIR/certs/key.pem"

        echo "ZS_SSL_DOMAIN=${ZS_SSL_DOMAIN}" >> "$REPO_DIR/.env"
        echo "SSL configured for domain ${ZS_SSL_DOMAIN} — cert files copied to $REPO_DIR/certs/"
        echo ""
    fi
fi

# Always ensure the certs directory exists so the ./certs:/certs:ro bind mount
# in docker-compose.yml never fails on a fresh clone with no certs provided.
mkdir -p "$REPO_DIR/certs"

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

# ── Force IPv4 for Docker Hub pulls ───────────────────────────────────────────
# Some hosts have an IPv6 route that's configured but not actually functional
# (common on cloud VMs and behind corporate proxies). Docker's image puller
# does a single dial with no IPv4 fallback, so a broken IPv6 path shows up as
# "dial tcp [ipv6]:443: i/o timeout" resolving registry-1.docker.io — instead
# of failing over. Pin the known Docker Hub hosts to their IPv4 address in
# /etc/hosts for the duration of the build only; removed on exit.
DOCKER_HUB_HOSTS=(registry-1.docker.io auth.docker.io production.cloudflare.docker.com)
HOSTS_MARKER="# added by zs-config deploy.sh (IPv4 pin, build-time only)"
_pinned_ipv4=0

_pin_ipv4_hosts() {
    [[ "$(uname)" == "Darwin" ]] && return 0
    command -v getent &>/dev/null || return 0

    local h ip
    for h in "${DOCKER_HUB_HOSTS[@]}"; do
        grep -qE "[[:space:]]${h}\$" /etc/hosts 2>/dev/null && continue
        ip="$(getent ahostsv4 "$h" 2>/dev/null | awk '{print $1; exit}')"
        [[ -n "$ip" ]] || continue
        echo "$ip	$h	$HOSTS_MARKER" | sudo tee -a /etc/hosts >/dev/null
        _pinned_ipv4=1
    done
    [[ "$_pinned_ipv4" -eq 1 ]] && echo "Pinned Docker Hub hosts to IPv4 in /etc/hosts (build-time only) to avoid broken-IPv6 pull timeouts."
}

_unpin_ipv4_hosts() {
    [[ "$_pinned_ipv4" -eq 1 ]] || return 0
    sudo sed -i.bak "/${HOSTS_MARKER//\//\\/}\$/d" /etc/hosts 2>/dev/null && sudo rm -f /etc/hosts.bak
}

cleanup_bundle() {
    : > "$BUNDLE"
    [[ -n "$DC_BACKUP" ]] && rm -f "$DC_BACKUP"
    _unpin_ipv4_hosts
}
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
    # On Linux, copy the host CA bundle (path varies by distro).
    # Debian/Ubuntu: /etc/ssl/certs/ca-certificates.crt
    # RHEL/Fedora/Rocky: /etc/pki/tls/certs/ca-bundle.crt
    if [[ -f /etc/ssl/certs/ca-certificates.crt ]]; then
        cp /etc/ssl/certs/ca-certificates.crt "$BUNDLE"
    elif [[ -f /etc/pki/tls/certs/ca-bundle.crt ]]; then
        cp /etc/pki/tls/certs/ca-bundle.crt "$BUNDLE"
    fi
fi

# ── Build ─────────────────────────────────────────────────────────────────────

_pin_ipv4_hosts

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
        if [[ -n "${ZS_SSL_DOMAIN:-}" ]]; then
            echo "zs-config is running at https://${ZS_SSL_DOMAIN}:8443"
            echo "(HTTP on port 8000 redirects to HTTPS)"
        else
            echo "zs-config is running at http://localhost:8000"
        fi
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
