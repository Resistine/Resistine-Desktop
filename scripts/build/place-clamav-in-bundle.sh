#!/bin/bash
# Sourced by build-distribution.sh — do not execute directly.
# Provides place_clamav_in_bundle() to copy ClamAV artifacts into Resistine.app.
#
# Expects these variables to be set by the caller:
#   CLAMAV_ARTIFACTS_DIR  — path to downloaded clamav-artifacts/
#   PYTHON_APP            — path to Resistine.app bundle

CLAMAV_AVAILABLE=true

place_clamav_in_bundle() {
    local BINARIES_DIR="$CLAMAV_ARTIFACTS_DIR/binaries"
    local LIB_DIR="$CLAMAV_ARTIFACTS_DIR/lib"

    # ── clamonacc → nested app bundle (ESF entitlements need a bundle) ──
    local CLAMAV_APP="$PYTHON_APP/Contents/Helpers/ResistineClamAV.app"
    mkdir -p "$CLAMAV_APP/Contents/MacOS"

    cp "$BINARIES_DIR/clamonacc" "$CLAMAV_APP/Contents/MacOS/clamonacc"
    echo "  - Placed clamonacc in ResistineClamAV.app"

    cat > "$CLAMAV_APP/Contents/Info.plist" << 'PLISTEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.resistine.desktop.clamonacc</string>
    <key>CFBundleName</key>
    <string>ResistineClamAV</string>
    <key>CFBundleExecutable</key>
    <string>clamonacc</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
</dict>
</plist>
PLISTEOF

    # ── Standalone binaries → Contents/Helpers/ ──
    mkdir -p "$PYTHON_APP/Contents/Helpers"
    for bin in clamd clamscan clamdscan freshclam; do
        if [ -f "$BINARIES_DIR/$bin" ]; then
            cp "$BINARIES_DIR/$bin" "$PYTHON_APP/Contents/Helpers/$bin"
            echo "  - Placed $bin in Contents/Helpers/"
        fi
    done

    # ── Shared libraries → Contents/Frameworks/ ──
    mkdir -p "$PYTHON_APP/Contents/Frameworks"
    for f in "$LIB_DIR"/*; do
        [ -e "$f" ] || continue
        cp -a "$f" "$PYTHON_APP/Contents/Frameworks/"
    done
    echo "  - Placed ClamAV libraries in Contents/Frameworks/"

    echo "  ClamAV components placed in bundle"
}
