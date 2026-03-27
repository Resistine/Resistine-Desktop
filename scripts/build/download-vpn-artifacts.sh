#!/bin/bash
set -e

# Download pre-built VPN artifacts from GitHub Actions
# Requires: GitHub CLI (gh) authenticated with access to Resistine/resistine-vpn-macos
#
# Usage:
#   ./download-vpn-artifacts.sh                  # download latest from main
#   ./download-vpn-artifacts.sh <run-id>         # download from specific run
#
# Then build with:
#   VPN_ARTIFACTS_DIR=scripts/build/vpn-artifacts ./scripts/build/build-distribution.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARTIFACTS_DIR="$SCRIPT_DIR/vpn-artifacts"
REPO="Resistine/resistine-vpn-macos"

# Check for gh CLI
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is required but not installed."
    echo "  Install: brew install gh"
    echo "  Then:    gh auth login"
    exit 1
fi

# Clean previous artifacts
rm -rf "$ARTIFACTS_DIR"
mkdir -p "$ARTIFACTS_DIR"

if [ -n "$1" ]; then
    echo "Downloading VPN artifacts from run $1..."
    gh run download "$1" --repo "$REPO" --dir "$ARTIFACTS_DIR"
else
    echo "Downloading latest VPN artifacts from main..."
    gh run download --repo "$REPO" --name vpn-macos-latest --dir "$ARTIFACTS_DIR"
fi

# gh run download nests files inside a subdirectory named after the artifact.
# Flatten so files are directly in ARTIFACTS_DIR.
NESTED=$(find "$ARTIFACTS_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)
if [ -n "$NESTED" ] && [ ! -f "$ARTIFACTS_DIR/resistine-vpn-cli" ]; then
    echo "  Flattening nested directory: $(basename "$NESTED")"
    mv "$NESTED"/* "$ARTIFACTS_DIR/" 2>/dev/null || true
    # Handle directories (like .systemextension bundle) separately
    find "$NESTED" -mindepth 1 -maxdepth 1 -type d -exec mv {} "$ARTIFACTS_DIR/" \; 2>/dev/null || true
    rmdir "$NESTED" 2>/dev/null || true
fi

# Verify expected files
if [ ! -f "$ARTIFACTS_DIR/resistine-vpn-cli" ]; then
    echo "Error: resistine-vpn-cli not found in downloaded artifacts"
    exit 1
fi

if [ ! -d "$ARTIFACTS_DIR/com.resistine.desktop.network-extension.systemextension" ]; then
    echo "Error: network extension not found in downloaded artifacts"
    exit 1
fi

echo ""
echo "VPN artifacts downloaded to: $ARTIFACTS_DIR"
echo ""
echo "Contents:"
ls -lh "$ARTIFACTS_DIR/"
echo ""
echo "Build with:"
echo "  VPN_ARTIFACTS_DIR=$ARTIFACTS_DIR ./scripts/build/build-distribution.sh"
