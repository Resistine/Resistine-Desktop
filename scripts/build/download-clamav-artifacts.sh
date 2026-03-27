#!/bin/bash
set -e

# Download pre-built ClamAV artifacts from GitHub Actions
# Requires: GitHub CLI (gh) authenticated with access to Resistine/ClamAV-Mac
#
# Usage:
#   ./download-clamav-artifacts.sh                  # download latest from main
#   ./download-clamav-artifacts.sh <run-id>         # download from specific run
#   ./download-clamav-artifacts.sh --check          # exit 0 if up-to-date, 1 if stale
#
# Called automatically by build-distribution.sh when artifacts are missing or stale.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARTIFACTS_DIR="$SCRIPT_DIR/clamav-artifacts"
REPO="Resistine/ClamAV-Mac"
VERSION_FILE="$ARTIFACTS_DIR/.clamav-version"

# Check for gh CLI
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is required but not installed."
    echo "  Install: brew install gh"
    echo "  Then:    gh auth login"
    exit 1
fi

# Query the latest artifact's commit SHA from CI
get_remote_sha() {
    gh api "repos/$REPO/actions/artifacts?name=clamav-macos-latest&per_page=1" \
        --jq '.artifacts[0].workflow_run.head_sha' 2>/dev/null || echo ""
}

# Read local version
get_local_sha() {
    if [ -f "$VERSION_FILE" ]; then
        cat "$VERSION_FILE"
    else
        echo ""
    fi
}

# --check mode: just report if up-to-date
if [ "$1" = "--check" ]; then
    LOCAL_SHA=$(get_local_sha)
    if [ -z "$LOCAL_SHA" ]; then
        echo "No local ClamAV artifacts"
        exit 1
    fi
    REMOTE_SHA=$(get_remote_sha)
    if [ -z "$REMOTE_SHA" ]; then
        echo "Could not query remote version (offline or no access)"
        exit 0  # don't block builds when offline
    fi
    if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
        echo "ClamAV artifacts up-to-date ($LOCAL_SHA)"
        exit 0
    else
        echo "ClamAV artifacts stale (local: ${LOCAL_SHA:0:12}, remote: ${REMOTE_SHA:0:12})"
        exit 1
    fi
fi

# Determine what to download
if [ -n "$1" ]; then
    echo "Downloading ClamAV artifacts from run $1..."
    DOWNLOAD_SHA=""
else
    # Check if we even need to download
    REMOTE_SHA=$(get_remote_sha)
    LOCAL_SHA=$(get_local_sha)

    if [ -n "$REMOTE_SHA" ] && [ "$LOCAL_SHA" = "$REMOTE_SHA" ] \
       && [ -f "$ARTIFACTS_DIR/binaries/clamonacc" ] \
       && [ -f "$ARTIFACTS_DIR/binaries/clamd" ]; then
        echo "ClamAV artifacts already up-to-date (${REMOTE_SHA:0:12})"
        exit 0
    fi

    if [ -n "$REMOTE_SHA" ]; then
        echo "Downloading ClamAV artifacts (${REMOTE_SHA:0:12})..."
    else
        echo "Downloading latest ClamAV artifacts from main..."
    fi
    DOWNLOAD_SHA="$REMOTE_SHA"
fi

# Clean previous artifacts
rm -rf "$ARTIFACTS_DIR"
mkdir -p "$ARTIFACTS_DIR"

if [ -n "$1" ]; then
    gh run download "$1" --repo "$REPO" --dir "$ARTIFACTS_DIR"
else
    gh run download --repo "$REPO" --name clamav-macos-latest --dir "$ARTIFACTS_DIR"
fi

# gh run download nests files inside a subdirectory named after the artifact.
# Flatten so files are directly in ARTIFACTS_DIR.
NESTED=$(find "$ARTIFACTS_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)
if [ -n "$NESTED" ] && [ ! -d "$ARTIFACTS_DIR/binaries" ]; then
    echo "  Flattening nested directory: $(basename "$NESTED")"
    mv "$NESTED"/* "$ARTIFACTS_DIR/" 2>/dev/null || true
    find "$NESTED" -mindepth 1 -maxdepth 1 -type d -exec mv {} "$ARTIFACTS_DIR/" \; 2>/dev/null || true
    rmdir "$NESTED" 2>/dev/null || true
fi

# Verify expected files
if [ ! -f "$ARTIFACTS_DIR/binaries/clamonacc" ]; then
    echo "Error: binaries/clamonacc not found in downloaded artifacts"
    exit 1
fi

if [ ! -f "$ARTIFACTS_DIR/binaries/clamd" ]; then
    echo "Error: binaries/clamd not found in downloaded artifacts"
    exit 1
fi

LIBCLAMAV_COUNT=$(find "$ARTIFACTS_DIR/lib" -name "libclamav*" 2>/dev/null | wc -l)
if [ "$LIBCLAMAV_COUNT" -eq 0 ]; then
    echo "Error: lib/libclamav* not found in downloaded artifacts"
    exit 1
fi

# Verify artifact checksums (if present)
if [ -f "$ARTIFACTS_DIR/checksums.txt" ]; then
    echo "  Verifying artifact checksums..."
    if (cd "$ARTIFACTS_DIR" && shasum -a 256 -c checksums.txt); then
        echo "  Checksums verified"
    else
        echo "Error: Checksum verification failed — artifacts may be corrupted"
        exit 1
    fi
fi

# Recreate library symlinks from manifest
# upload-artifact doesn't preserve symlinks, so CI records them in symlinks.txt
if [ -f "$ARTIFACTS_DIR/lib/symlinks.txt" ]; then
    echo "  Recreating library symlinks..."
    while IFS=' ' read -r link_name _ link_target; do
        [ -n "$link_name" ] && [ -n "$link_target" ] || continue
        (cd "$ARTIFACTS_DIR/lib" && ln -sf "$link_target" "$link_name")
        echo "    $link_name -> $link_target"
    done < "$ARTIFACTS_DIR/lib/symlinks.txt"
    rm "$ARTIFACTS_DIR/lib/symlinks.txt"
fi

# Save version for staleness checks
if [ -n "$DOWNLOAD_SHA" ]; then
    echo "$DOWNLOAD_SHA" > "$VERSION_FILE"
elif [ -n "$1" ]; then
    # For specific run IDs, query the run's head SHA
    RUN_SHA=$(gh api "repos/$REPO/actions/runs/$1" --jq '.head_sha' 2>/dev/null || echo "")
    if [ -n "$RUN_SHA" ]; then
        echo "$RUN_SHA" > "$VERSION_FILE"
    fi
fi

echo ""
echo "ClamAV artifacts downloaded to: $ARTIFACTS_DIR"
ls -lhR "$ARTIFACTS_DIR/"
