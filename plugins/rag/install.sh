#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_WORKSPACE="${1:-$HOME/.nanobot/workspace}"

echo "=================================================="
echo "    Nanobot RAG Plugin Installer & Verifier"
echo "=================================================="

# Check python
if ! command -v python3 &>/dev/null; then
    echo "[-] Error: python3 is not installed."
    exit 1
fi

echo "[+] Python runtime: $(python3 --version)"

# Check plugin manifest & server
if [[ ! -f "$SCRIPT_DIR/plugin.json" || ! -f "$SCRIPT_DIR/server.py" ]]; then
    echo "[-] Error: Invalid plugin directory structure at $SCRIPT_DIR"
    exit 1
fi

echo "[+] Creating plugins directory in target workspace: $TARGET_WORKSPACE"
mkdir -p "$TARGET_WORKSPACE/plugins"

DEST_DIR="$TARGET_WORKSPACE/plugins/rag"
echo "[+] Copying plugin into $DEST_DIR..."
rm -rf "$DEST_DIR"
cp -r "$SCRIPT_DIR" "$DEST_DIR"

echo "[+] Plugin installed successfully into $DEST_DIR"
echo ""
echo "To enable this plugin in your workspace, add to nanobot.json:"
echo '  "plugins": {'
echo '    "enabled": ["rag"]'
echo '  }'
echo "=================================================="
