#!/usr/bin/env bash
# Regenerates LICENSE-3rd-Party.md at the repo root from:
#   1. scripts/build/license-3rd-party-header.md (intro, hand-maintained)
#   2. pip-licenses output for every installed Python package
#   3. scripts/build/license-3rd-party-bundled.md (non-pip components,
#      hand-maintained)
#
# Run this from an activated venv that has the production dependencies
# installed (i.e., the same env that ships in a release build). It is
# invoked automatically from the release workflow before each platform
# artifact is uploaded, so the generated file always reflects the exact
# dep set of that release.
#
# Manual usage:
#   source .venv/bin/activate
#   pip install pip-licenses             # if not already installed
#   ./scripts/build/generate-license-third-party.sh
#
# Adding this to a new release job (Linux, Windows, etc.):
# Drop these three steps into the release workflow AFTER the platform's
# requirements are installed and BEFORE the build step:
#
#   - name: Install pip-licenses
#     run: pip install "pip-licenses>=4.0.0"
#
#   - name: Generate third-party license file
#     run: ./scripts/build/generate-license-third-party.sh
#
#   - name: Verify LICENSE-3rd-Party.md is committed and up to date
#     run: git diff --exit-code LICENSE-3rd-Party.md
#
# Note: the committed LICENSE-3rd-Party.md represents one canonical platform's
# install. If different platforms install meaningfully different dep sets,
# regenerate on the platform you consider canonical (currently macOS) and
# skip the freshness diff on other platforms.
#
# Author: Resistine Team
# Copyright (c) Resistine 2026
# Licensed under the GNU General Public License v2 or later

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

HEADER="$SCRIPT_DIR/license-3rd-party-header.md"
BUNDLED="$SCRIPT_DIR/license-3rd-party-bundled.md"
OUT="$REPO_ROOT/LICENSE-3rd-Party.md"

# Sanity-check templates exist
for f in "$HEADER" "$BUNDLED"; do
    if [ ! -f "$f" ]; then
        echo "ERROR: required template missing: $f" >&2
        exit 1
    fi
done

# Sanity-check pip-licenses is installed in the current env
if ! python -m pip show pip-licenses >/dev/null 2>&1; then
    echo "ERROR: pip-licenses not installed in current environment." >&2
    echo "Install with: pip install pip-licenses" >&2
    exit 1
fi

echo "Generating $OUT ..."

# Use a temp file so we never leave a half-written LICENSE-3rd-Party.md
# behind if pip-licenses fails partway through.
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

{
    cat "$HEADER"
    printf '\n## Python Dependencies\n\n'
    # --with-urls: project home page in the table
    # --with-license-file: not used (too verbose; full text bloats the file)
    # --format=markdown: pretty table
    # --no-license-path: keep the table clean
    # --fail-on blocks licenses incompatible with our GPL-2.0-or-later
    # distribution. The list covers:
    #   - AGPL family: one-way compatibility (we'd be forced to AGPL too)
    #   - SSPL: not OSI-approved, restricts SaaS-style redistribution
    #   - BUSL: source-available but not OSS; converts to permissive only
    #     after a delay, can't be relied on
    #   - Commons Clause: rider that strips commercial use from an otherwise
    #     OSS license
    # If a new pip dep introduces any of these, the build fails here with a
    # clear "fail on license" error rather than silently shipping a license
    # we can't legally combine with our codebase. Partial-match catches
    # variants like "AGPLv3", "Affero General Public License v3", etc.
    python -m piplicenses \
        --format=markdown \
        --with-urls \
        --order=name \
        --partial-match \
        --fail-on "AGPL;Affero General Public License;SSPL;Server Side Public License;BUSL;Business Source License;Commons Clause"
    printf '\n'
    cat "$BUNDLED"
} > "$TMP"

mv "$TMP" "$OUT"
trap - EXIT

echo "  ✓ Wrote $OUT ($(wc -l < "$OUT" | xargs) lines)"
