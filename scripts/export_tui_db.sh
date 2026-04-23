#!/usr/bin/env bash
# export_tui_db.sh — Export the database and encryption key from a local
# TUI-based zs-config install so they can be imported into the web UI.
#
# Usage:
#   ./scripts/export_tui_db.sh [output_dir]
#
# Output files (written to output_dir, default: current directory):
#   zscaler.db   — SQLite database
#   secret.key   — Fernet encryption key (only if found)
#
# After running this script, upload both files via Admin → Settings →
# Import Database in the zs-config web UI.

set -euo pipefail

OUTPUT_DIR="${1:-.}"
mkdir -p "$OUTPUT_DIR"

# ── Locate the database ───────────────────────────────────────────────────────

find_db() {
    local candidates=(
        "$HOME/.local/share/zs-config/zscaler.db"
        "$HOME/.local/share/z-config/zscaler.db"
        "$HOME/.local/share/zscaler-cli/zscaler.db"
        "$HOME/Library/Application Support/zs-config/zscaler.db"
        "$HOME/Library/Application Support/z-config/zscaler.db"
        "$HOME/Library/Application Support/zscaler-cli/zscaler.db"
    )
    for path in "${candidates[@]}"; do
        if [[ -f "$path" ]]; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

# ── Locate the encryption key ─────────────────────────────────────────────────

find_key() {
    local candidates=(
        "$HOME/.config/zs-config/secret.key"
        "$HOME/.config/z-config/secret.key"
        "$HOME/.config/zscaler-cli/secret.key"
    )
    for path in "${candidates[@]}"; do
        if [[ -f "$path" ]]; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo "Looking for zs-config TUI database..."

if DB_PATH=$(find_db); then
    echo "  Found: $DB_PATH"
    cp "$DB_PATH" "$OUTPUT_DIR/zscaler.db"
    echo "  Exported → $OUTPUT_DIR/zscaler.db"
else
    echo "ERROR: No zs-config database found. Tried:"
    echo "  ~/.local/share/zs-config/zscaler.db"
    echo "  ~/.local/share/z-config/zscaler.db"
    echo "  ~/Library/Application Support/zs-config/zscaler.db"
    echo ""
    echo "If your database is in a custom location, copy it manually."
    exit 1
fi

echo ""
echo "Looking for encryption key..."

if KEY_PATH=$(find_key); then
    echo "  Found: $KEY_PATH"
    cp "$KEY_PATH" "$OUTPUT_DIR/secret.key"
    echo "  Exported → $OUTPUT_DIR/secret.key"
else
    echo "  No key file found (checked ~/.config/zs-config/secret.key and legacy paths)."
    echo "  If your tenants have encrypted credentials, set ZSCALER_SECRET_KEY in the"
    echo "  container environment instead of uploading a key file."
fi

echo ""
echo "Done. Upload these files via Admin → Settings → Import Database."
