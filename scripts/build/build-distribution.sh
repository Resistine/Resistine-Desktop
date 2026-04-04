#!/bin/bash
set -e

# Resistine Distribution Build Script
# Builds, signs with Developer ID, creates DMG, notarizes, and staples.
# Use build-installer.sh for local development/testing (Apple Development signing).
# Use this script for public distribution (Developer ID + notarization).

echo "=== Resistine Distribution Build ==="
echo "Building for public distribution (Developer ID + Notarization)"
echo ""

# Project paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_UI_PATH="$(cd "$SCRIPT_DIR/../.." && pwd)"
VPN_PROJECT_PATH="$PYTHON_UI_PATH/vpn-apple"

# Validate paths exist
echo "Checking project structure..."
if [ ! -d "$PYTHON_UI_PATH" ]; then
    echo "  Error: Python UI directory not found at: $PYTHON_UI_PATH"
    exit 1
fi

echo "  Found Python UI: $PYTHON_UI_PATH"
echo ""

# Build configuration
BUILD_DIR="$VPN_PROJECT_PATH/build"
DIST_DIR="$PYTHON_UI_PATH/dist"
APP_NAME="Resistine"
BUNDLE_ID="com.resistine.desktop"

# ============================================================
# Step 1: Verify Developer ID certificate (REQUIRED for distribution)
# ============================================================
echo "Step 1: Verifying Developer ID certificate..."

SIGN_IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | grep "Developer ID Application" | head -1 | awk '{print $2}')

if [ -z "$SIGN_IDENTITY" ]; then
    echo "  Error: No Developer ID Application certificate found."
    echo "  Distribution builds REQUIRE a Developer ID certificate."
    echo "  Use build-installer.sh for local development instead."
    exit 1
fi

SIGN_NAME=$(security find-identity -v -p codesigning 2>/dev/null | grep "$SIGN_IDENTITY" | sed 's/.*"\(.*\)".*/\1/')
echo "  Signing with: $SIGN_NAME"

TEAM_ID=$(security find-identity -v -p codesigning 2>/dev/null | grep "$SIGN_IDENTITY" | grep -o '([A-Z0-9]*)' | tr -d '()' | head -1)
echo "  Team ID: $TEAM_ID"

if [ -z "$TEAM_ID" ]; then
    echo "  Error: Could not detect Team ID from certificate."
    exit 1
fi

# Verify notarization credentials are stored
echo "  Checking notarization credentials..."
if ! xcrun notarytool history --keychain-profile "resistine-notarize" > /dev/null 2>&1; then
    echo ""
    echo "  Warning: Notarization credentials not found."
    echo "  Store them with:"
    echo "    xcrun notarytool store-credentials \"resistine-notarize\" \\"
    echo "      --apple-id \"jackie@resistine.com\" \\"
    echo "      --team-id \"$TEAM_ID\" \\"
    echo "      --password \"<your-app-specific-password>\""
    echo ""
    echo "  Press Enter to continue without notarization, or Ctrl+C to cancel..."
    read -r
    SKIP_NOTARIZE=true
else
    echo "  Notarization credentials found"
    SKIP_NOTARIZE=false
fi

echo ""

# ============================================================
# Step 2: Obtain Swift Components (VPN)
# ============================================================
# Artifacts are auto-downloaded from Resistine/resistine-vpn-macos CI.
# The script detects stale artifacts and re-downloads when a newer
# build is available. Set VPN_ARTIFACTS_DIR to override the path.
# Fallback: build locally from vpn-apple/ if present.
# ============================================================

VPN_ARTIFACTS_DIR="${VPN_ARTIFACTS_DIR:-$SCRIPT_DIR/vpn-artifacts}"

echo "Step 2: Checking VPN artifacts..."

# Auto-download if missing or stale
if [ -f "$SCRIPT_DIR/download-vpn-artifacts.sh" ] && command -v gh &> /dev/null; then
    if ! "$SCRIPT_DIR/download-vpn-artifacts.sh" --check 2>/dev/null; then
        echo "  VPN artifacts missing or stale — downloading from CI..."
        "$SCRIPT_DIR/download-vpn-artifacts.sh" || {
            echo "  Warning: Auto-download failed"
        }
    else
        echo "  VPN artifacts up-to-date"
    fi
fi

if [ -f "$VPN_ARTIFACTS_DIR/resistine-vpn-cli" ] && \
   [ -d "$VPN_ARTIFACTS_DIR/com.resistine.desktop.network-extension.systemextension" ]; then
    echo "  Using pre-built VPN artifacts from $VPN_ARTIFACTS_DIR"
    USE_PREBUILT_VPN=true
elif [ -d "$VPN_PROJECT_PATH" ]; then
    echo "  No pre-built artifacts — building Swift components locally..."
    cd "$VPN_PROJECT_PATH"

    rm -rf build/

    xcodebuild \
      -project wireguard-apple.xcodeproj \
      -scheme wireguard-apple \
      -configuration Release \
      -archivePath "$BUILD_DIR/wireguard-apple.xcarchive" \
      archive \
      -allowProvisioningUpdates

    echo "  Swift components built"
    USE_PREBUILT_VPN=false
else
    echo "  Error: No VPN artifacts and no vpn-apple project to build from."
    echo "  Install gh CLI (brew install gh) and authenticate (gh auth login)."
    exit 1
fi

# ============================================================
# Step 2b: Obtain ClamAV Components
# ============================================================
# Artifacts are auto-downloaded from Resistine/ClamAV-Mac CI.
# The script detects stale artifacts and re-downloads when a newer
# build is available. Set CLAMAV_ARTIFACTS_DIR to override the path.
# ============================================================

CLAMAV_ARTIFACTS_DIR="${CLAMAV_ARTIFACTS_DIR:-$SCRIPT_DIR/clamav-artifacts}"

echo "Step 2b: Checking ClamAV artifacts..."

# Auto-download if missing or stale
if [ -f "$SCRIPT_DIR/download-clamav-artifacts.sh" ] && command -v gh &> /dev/null; then
    if ! "$SCRIPT_DIR/download-clamav-artifacts.sh" --check 2>/dev/null; then
        echo "  ClamAV artifacts missing or stale — downloading from CI..."
        "$SCRIPT_DIR/download-clamav-artifacts.sh" || {
            echo "  Warning: Auto-download failed"
        }
    else
        echo "  ClamAV artifacts up-to-date"
    fi
fi

CLAMAV_AVAILABLE=false
if [ -d "$CLAMAV_ARTIFACTS_DIR/binaries" ]; then
    CLAMAV_AVAILABLE=true
fi

# ============================================================
# Step 3: Build Python UI with PyInstaller
# ============================================================
echo ""
echo "Step 3: Building Python UI..."
cd "$PYTHON_UI_PATH"

if [ ! -d ".venv" ]; then
    echo "  - Creating virtual environment..."
    # Use python.org universal2 build for broad macOS compatibility (target 13.0 Ventura)
    # Do NOT use Homebrew Python which targets only the current macOS version
    # Auto-detect the latest python.org install instead of hardcoding a version
    PYTHONORG=$(ls -d /Library/Frameworks/Python.framework/Versions/3.*/bin/python3.* 2>/dev/null | grep -v config | sort -t/ -k7 -V | tail -1)
    if [ -n "$PYTHONORG" ] && [ -f "$PYTHONORG" ]; then
        echo "  Using python.org Python: $PYTHONORG"
        "$PYTHONORG" -m venv .venv
    else
        echo "  Warning: python.org Python not found"
        echo "  Falling back to system python3 (may have limited macOS compatibility)"
        python3 -m venv .venv
    fi
fi

echo "  - Installing dependencies..."
source .venv/bin/activate
export MACOSX_DEPLOYMENT_TARGET=13.0  # Ensure compiled extensions target macOS 13+ (Ventura)
pip install -q -r scripts/requirements/requirements-mac.txt

if [ ! -f "packaging/Resistine.spec" ]; then
    echo "  Error: packaging/Resistine.spec not found in $PYTHON_UI_PATH"
    exit 1
fi

rm -rf dist/Resistine dist/Resistine.app

echo "  - Building with PyInstaller..."
pyinstaller packaging/Resistine.spec --noconfirm

echo "  Python UI built"

# ============================================================
# Step 4: Place VPN components directly in Resistine.app bundle
# ============================================================
# Apple bundle structure requirements (from Apple documentation):
#   - App Extensions (.appex): Contents/PlugIns/
#   - Helper Tools / CLI: Contents/MacOS/
#   - Frameworks: Contents/Frameworks/
#
# CRITICAL: Do NOT nest bundles inside Contents/Resources/. macOS extension
# discovery looks for components relative to the parent bundle. If the XPC
# service is nested inside wireguard-apple.app, it will look for the network
# extension inside wireguard-apple.app/Contents/PlugIns/ instead of the main
# Resistine.app/Contents/PlugIns/.
echo ""
echo "Step 4: Placing VPN components in main app bundle..."

PYTHON_APP="$DIST_DIR/$APP_NAME.app"

if [ ! -d "$PYTHON_APP" ]; then
    echo "  Error: Python app bundle not found at $PYTHON_APP"
    exit 1
fi

# Resolve VPN component sources (pre-built artifacts or local archive)
if [ "$USE_PREBUILT_VPN" = true ]; then
    CLI_SOURCE="$VPN_ARTIFACTS_DIR/resistine-vpn-cli"
    NE_SOURCE="$VPN_ARTIFACTS_DIR/com.resistine.desktop.network-extension.systemextension"
else
    VPN_ARCHIVE="$BUILD_DIR/wireguard-apple.xcarchive/Products/Applications/wireguard-apple.app"

    if [ ! -d "$VPN_ARCHIVE" ]; then
        echo "  Error: VPN archive not found at $VPN_ARCHIVE"
        exit 1
    fi

    CLI_SOURCE=$(find "$VPN_ARCHIVE" -name "resistine-vpn-cli" -type f | grep -v "dSYM" | grep "/MacOS/" | head -1)
    if [ -z "$CLI_SOURCE" ] || [ ! -f "$CLI_SOURCE" ]; then
        echo "  Error: resistine-vpn-cli not found in archive"
        exit 1
    fi

    NE_SOURCE=$(find "$VPN_ARCHIVE" -name "*network-extension*" \( -name "*.appex" -o -name "*.systemextension" \) -type d | grep -v "dSYM" | head -1)
    if [ -z "$NE_SOURCE" ]; then
        echo "  Error: Network Extension not found in archive"
        exit 1
    fi
fi

# Create Apple-standard directories
mkdir -p "$PYTHON_APP/Contents/PlugIns"
mkdir -p "$PYTHON_APP/Contents/Library/SystemExtensions"

# --- Copy CLI to Contents/MacOS/ as a Bundle ---
# To support restricted entitlements (App Groups) in the CLI, it must have a
# provisioning profile embedded. Standalone binaries cannot easily have embedded
# profiles, so we wrap it in a nested bundle: ResistineCLI.app

echo "  - Packaging resistine-vpn-cli into nested bundle..."
CLI_APP="$PYTHON_APP/Contents/MacOS/ResistineCLI.app"
mkdir -p "$CLI_APP/Contents/MacOS"

echo "    Found CLI at: $CLI_SOURCE"
cp "$CLI_SOURCE" "$CLI_APP/Contents/MacOS/resistine-vpn-cli"

# --- Copy Network Extension to Contents/Library/SystemExtensions/ ---
# CRITICAL: System Extensions MUST use .systemextension extension, not .appex!
echo "  - Copying network-extension to Contents/Library/SystemExtensions/..."

# Use the full bundle name: com.resistine.desktop.network-extension.systemextension
DEST_EXTENSION="$PYTHON_APP/Contents/Library/SystemExtensions/com.resistine.desktop.network-extension.systemextension"
mkdir -p "$PYTHON_APP/Contents/Library/SystemExtensions"
rm -rf "$DEST_EXTENSION"
cp -R "$NE_SOURCE" "$DEST_EXTENSION"

# Verify placement
if [ ! -d "$PYTHON_APP/Contents/Library/SystemExtensions/com.resistine.desktop.network-extension.systemextension" ]; then
    echo "  Error: System Extension not in Contents/Library/SystemExtensions/"
    exit 1
fi

# Create minimal Info.plist for the CLI bundle
cat > "$CLI_APP/Contents/Info.plist" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.resistine.desktop.vpnxpc</string>
    <key>CFBundleName</key>
    <string>ResistineCLI</string>
    <key>CFBundleExecutable</key>
    <string>resistine-vpn-cli</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
</dict>
</plist>
PLISTEOF

# ============================================================
# Step 4b: Place ClamAV components in app bundle
# ============================================================
echo ""
if [ -d "$CLAMAV_ARTIFACTS_DIR/binaries" ]; then
    echo "Step 4b: Placing ClamAV components in app bundle..."

    CLAMAV_BINARIES_DIR="$CLAMAV_ARTIFACTS_DIR/binaries"
    CLAMAV_LIB_DIR="$CLAMAV_ARTIFACTS_DIR/lib"

    # clamonacc → nested app bundle (ESF entitlements need a bundle)
    CLAMAV_APP="$PYTHON_APP/Contents/Helpers/ResistineClamAV.app"
    mkdir -p "$CLAMAV_APP/Contents/MacOS"

    cp "$CLAMAV_BINARIES_DIR/clamonacc" "$CLAMAV_APP/Contents/MacOS/clamonacc"
    echo "  - Placed clamonacc in ResistineClamAV.app"

    cat > "$CLAMAV_APP/Contents/Info.plist" << 'PLISTEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.resistine.clamonacc</string>
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

    # Standalone binaries → Contents/Helpers/
    mkdir -p "$PYTHON_APP/Contents/Helpers"
    for bin in clamd clamscan clamdscan freshclam; do
        if [ -f "$CLAMAV_BINARIES_DIR/$bin" ]; then
            cp "$CLAMAV_BINARIES_DIR/$bin" "$PYTHON_APP/Contents/Helpers/$bin"
            echo "  - Placed $bin in Contents/Helpers/"
        fi
    done

    # CVD signature-verification certs → Contents/certs/
    if [ -d "$CLAMAV_ARTIFACTS_DIR/certs" ]; then
        mkdir -p "$PYTHON_APP/Contents/certs"
        cp "$CLAMAV_ARTIFACTS_DIR/certs/"* "$PYTHON_APP/Contents/certs/"
        echo "  - Placed CVD verification certs in Contents/certs/"
    fi

    # Shared libraries → Contents/Frameworks/ (skip static archives, deduplicate symlinks)
    mkdir -p "$PYTHON_APP/Contents/Frameworks"
    for f in "$CLAMAV_LIB_DIR"/*; do
        [ -e "$f" ] || continue
        # Skip static archives — only needed at compile time, not runtime
        case "$f" in *.a) continue ;; esac
        # Only copy the real file for each library; recreate version symlinks
        if [ -L "$f" ]; then
            cp -a "$f" "$PYTHON_APP/Contents/Frameworks/"
        else
            cp "$f" "$PYTHON_APP/Contents/Frameworks/"
        fi
    done
    echo "  - Placed ClamAV libraries in Contents/Frameworks/"

    # ── Fix dylib rpaths ──
    # CI-built binaries have hardcoded rpaths from the build machine.
    # Rewrite them so binaries find dylibs in Contents/Frameworks/ at runtime.
    echo "  - Fixing ClamAV dylib rpaths..."

    FRAMEWORKS_RELATIVE="@executable_path/../Frameworks"

    # Fix binaries in Contents/Helpers/
    for bin in clamd clamscan clamdscan freshclam; do
        BIN_PATH="$PYTHON_APP/Contents/Helpers/$bin"
        [ -f "$BIN_PATH" ] || continue

        # Remove all existing LC_RPATH entries
        for old_rpath in $(otool -l "$BIN_PATH" 2>/dev/null | awk '/cmd LC_RPATH/{found=1} found && /path /{print $2; found=0}'); do
            install_name_tool -delete_rpath "$old_rpath" "$BIN_PATH" 2>/dev/null || true
        done

        # Add the correct rpath
        install_name_tool -add_rpath "$FRAMEWORKS_RELATIVE" "$BIN_PATH" 2>/dev/null || true

        # Rewrite hardcoded Homebrew load commands to @rpath
        for homebrew_ref in $(otool -L "$BIN_PATH" 2>/dev/null | awk '/\/opt\/homebrew/{print $1}'); do
            install_name_tool -change "$homebrew_ref" "@rpath/$(basename "$homebrew_ref")" "$BIN_PATH" 2>/dev/null || true
        done
        echo "    Fixed rpath: $bin → $FRAMEWORKS_RELATIVE"
    done

    # Fix clamonacc in nested bundle (different relative path)
    CLAMONACC_PATH="$CLAMAV_APP/Contents/MacOS/clamonacc"
    if [ -f "$CLAMONACC_PATH" ]; then
        CLAMONACC_FRAMEWORKS="@executable_path/../../../../Frameworks"
        for old_rpath in $(otool -l "$CLAMONACC_PATH" 2>/dev/null | awk '/cmd LC_RPATH/{found=1} found && /path /{print $2; found=0}'); do
            install_name_tool -delete_rpath "$old_rpath" "$CLAMONACC_PATH" 2>/dev/null || true
        done
        install_name_tool -add_rpath "$CLAMONACC_FRAMEWORKS" "$CLAMONACC_PATH" 2>/dev/null || true
        # Rewrite hardcoded Homebrew load commands to @rpath
        for homebrew_ref in $(otool -L "$CLAMONACC_PATH" 2>/dev/null | awk '/\/opt\/homebrew/{print $1}'); do
            install_name_tool -change "$homebrew_ref" "@rpath/$(basename "$homebrew_ref")" "$CLAMONACC_PATH" 2>/dev/null || true
        done
        echo "    Fixed rpath: clamonacc → $CLAMONACC_FRAMEWORKS"
    fi

    # Fix dylibs that reference other dylibs via @rpath
    for dylib in "$PYTHON_APP/Contents/Frameworks"/lib*.dylib; do
        [ -f "$dylib" ] || continue
        [ -L "$dylib" ] && continue  # Skip symlinks

        # Remove hardcoded rpaths
        for old_rpath in $(otool -l "$dylib" 2>/dev/null | awk '/cmd LC_RPATH/{found=1} found && /path /{print $2; found=0}'); do
            install_name_tool -delete_rpath "$old_rpath" "$dylib" 2>/dev/null || true
        done

        # Set the dylib's own install name to @rpath/name
        DYLIB_NAME=$(basename "$dylib")
        install_name_tool -id "@rpath/$DYLIB_NAME" "$dylib" 2>/dev/null || true

        # Add rpath for peer dylib resolution
        install_name_tool -add_rpath "@loader_path" "$dylib" 2>/dev/null || true

        # Rewrite hardcoded Homebrew load commands to @rpath
        for homebrew_ref in $(otool -L "$dylib" 2>/dev/null | awk '/\/opt\/homebrew/{print $1}'); do
            install_name_tool -change "$homebrew_ref" "@rpath/$(basename "$homebrew_ref")" "$dylib" 2>/dev/null || true
        done
    done
    echo "    Fixed dylib install names and rpaths"

    # LaunchDaemon plists → Contents/Library/LaunchDaemons/
    # Registered at runtime via SMAppService (no manual launchctl needed).
    LAUNCHD_SRC="$CLAMAV_ARTIFACTS_DIR/launchd"
    if [ -d "$LAUNCHD_SRC" ]; then
        mkdir -p "$PYTHON_APP/Contents/Library/LaunchDaemons"
        cp "$LAUNCHD_SRC/"*.plist "$PYTHON_APP/Contents/Library/LaunchDaemons/"
        echo "  - Placed launchd plists in Contents/Library/LaunchDaemons/"
    else
        echo "  - Warning: No launchd plists found in artifacts"
    fi

    echo "  ClamAV components placed in bundle"
else
    echo "Step 4b: Skipping ClamAV — no artifacts found"
    echo "  Run: scripts/build/download-clamav-artifacts.sh"
    CLAMAV_AVAILABLE=false
fi

# ============================================================
# Step 5: Embed Developer ID provisioning profiles & sign
# ============================================================
echo ""
echo "Step 5: Embedding Developer ID provisioning profiles & signing..."

PROFILES_DIR="$PYTHON_UI_PATH/provisioning-profiles"
NE_PROFILE="$PROFILES_DIR/Mac_Network_Ext.provisionprofile"
XPC_PROFILE="$PROFILES_DIR/Mac_VPNXPC.provisionprofile"
MAIN_PROFILE="$PROFILES_DIR/Mac_Desktop.provisionprofile"
CLAMONACC_PROFILE="$PROFILES_DIR/Mac_ClamOnAcc.provisionprofile"

# Validate Profiles
if [ ! -f "$NE_PROFILE" ]; then
    echo "  Error: Network Extension Developer ID profile not found at: $NE_PROFILE"
    exit 1
fi

if [ ! -f "$XPC_PROFILE" ]; then
    echo "  Error: VPNXPC Service Developer ID profile not found at: $XPC_PROFILE"
    exit 1
fi

if [ ! -f "$MAIN_PROFILE" ]; then
    echo "  Error: Main App Developer ID profile not found at: $MAIN_PROFILE"
    exit 1
fi

# Embedding Developer ID profiles into components
echo "  - Embedding Developer ID profile into system extension..."
cp "$NE_PROFILE" "$PYTHON_APP/Contents/Library/SystemExtensions/com.resistine.desktop.network-extension.systemextension/Contents/embedded.provisionprofile"

echo "  - Embedding Developer ID profile into main app..."
cp "$MAIN_PROFILE" "$PYTHON_APP/Contents/embedded.provisionprofile"

echo "  - Embedding XPC profile into CLI bundle..."
cp "$XPC_PROFILE" "$CLI_APP/Contents/embedded.provisionprofile"

# Embed ESF provisioning profile into ResistineClamAV.app (clamonacc)
if [ "$CLAMAV_AVAILABLE" = true ] && [ -d "$PYTHON_APP/Contents/Helpers/ResistineClamAV.app" ]; then
    if [ -f "$CLAMONACC_PROFILE" ]; then
        echo "  - Embedding ESF profile into ResistineClamAV.app..."
        cp "$CLAMONACC_PROFILE" "$PYTHON_APP/Contents/Helpers/ResistineClamAV.app/Contents/embedded.provisionprofile"
    else
        echo "  - Warning: ClamOnAcc provisioning profile not found at $CLAMONACC_PROFILE"
        echo "    clamonacc will not be able to register as an ESF client"
    fi
fi

# Create symlink for compatibility
# Python code expects resistine-vpn-cli at ../MacOS/resistine-vpn-cli
echo "  - Creating symlink for CLI..."
ln -sf "ResistineCLI.app/Contents/MacOS/resistine-vpn-cli" "$PYTHON_APP/Contents/MacOS/resistine-vpn-cli"

# --- Copy Sparkle.framework for auto-updates ---
echo "  - Copying Sparkle.framework..."
SPARKLE_SOURCE="$PYTHON_UI_PATH/frameworks/Sparkle.framework"
if [ -d "$SPARKLE_SOURCE" ]; then
    mkdir -p "$PYTHON_APP/Contents/Frameworks"
    cp -R "$SPARKLE_SOURCE" "$PYTHON_APP/Contents/Frameworks/Sparkle.framework"
    echo "    Sparkle.framework copied"
else
    echo "    Warning: Sparkle.framework not found at $SPARKLE_SOURCE — skipping auto-update"
fi


# Locate entitlements files
ENTITLEMENTS_FILE="$PYTHON_UI_PATH/packaging/Resistine.entitlements"

NE_DIST_ENTITLEMENTS="/tmp/ne-distribution.entitlements.plist"
CLI_DIST_ENTITLEMENTS="/tmp/cli-distribution.entitlements.plist"

echo "  - Generating distribution entitlements..."

# NE Entitlements
cat > "$NE_DIST_ENTITLEMENTS" << ENTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>com.apple.application-identifier</key>
	<string>${TEAM_ID}.com.resistine.desktop.network-extension</string>
	<key>com.apple.developer.team-identifier</key>
	<string>${TEAM_ID}</string>
	<key>com.apple.developer.networking.networkextension</key>
	<array>
		<string>packet-tunnel-provider-systemextension</string>
	</array>
	<key>com.apple.security.app-sandbox</key>
	<true/>
	<key>com.apple.security.application-groups</key>
	<array>
		<string>group.Resistine.WireguardTest</string>
		<string>${TEAM_ID}.*</string>
	</array>
	<key>com.apple.security.network.client</key>
	<true/>
	<key>com.apple.security.network.server</key>
	<true/>
	<key>keychain-access-groups</key>
	<array>
		<string>${TEAM_ID}.*</string>
	</array>
</dict>
</plist>
ENTEOF

# CLI Entitlements (referencing the bundle ID)
cat > "$CLI_DIST_ENTITLEMENTS" << ENTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>com.apple.application-identifier</key>
	<string>${TEAM_ID}.com.resistine.desktop.vpnxpc</string>
	<key>com.apple.developer.team-identifier</key>
	<string>${TEAM_ID}</string>
	<key>com.apple.developer.networking.networkextension</key>
	<array>
		<string>packet-tunnel-provider-systemextension</string>
	</array>
	<key>com.apple.security.app-sandbox</key>
	<true/>
	<key>com.apple.security.application-groups</key>
	<array>
		<string>group.Resistine.WireguardTest</string>
		<string>${TEAM_ID}.*</string>
	</array>
	<key>com.apple.security.network.client</key>
	<true/>
	<key>keychain-access-groups</key>
	<array>
		<string>${TEAM_ID}.*</string>
	</array>
</dict>
</plist>
ENTEOF


ENTITLEMENTS_FLAG=""
if [ -f "$ENTITLEMENTS_FILE" ]; then
    ENTITLEMENTS_FLAG="--entitlements $ENTITLEMENTS_FILE"
fi

# --- Sign innermost components first, then work outward ---
# Order matters: sign binaries inside bundles before signing the bundle itself.

# 5-clamav: Sign ClamAV components (innermost first)
if [ "$CLAMAV_AVAILABLE" = true ]; then
    echo "  - Signing ClamAV components with Developer ID..."

    CLAMAV_ENTITLEMENTS="$CLAMAV_ARTIFACTS_DIR/entitlements.plist"

    # Sign clamonacc with ESF entitlements
    if [ -f "$CLAMAV_ENTITLEMENTS" ]; then
        codesign --force --sign "$SIGN_IDENTITY" \
            --options runtime --timestamp \
            --entitlements "$CLAMAV_ENTITLEMENTS" \
            "$PYTHON_APP/Contents/Helpers/ResistineClamAV.app/Contents/MacOS/clamonacc" || {
            echo "    clamonacc signing failed"
            exit 1
        }
    fi

    # Sign ResistineClamAV.app bundle (preserve ESF entitlements for clamonacc)
    codesign --force --sign "$SIGN_IDENTITY" \
        --options runtime --timestamp \
        ${CLAMAV_ENTITLEMENTS:+--entitlements "$CLAMAV_ENTITLEMENTS"} \
        "$PYTHON_APP/Contents/Helpers/ResistineClamAV.app" || {
        echo "    ResistineClamAV.app signing failed"
        exit 1
    }

    # Sign other ClamAV binaries (hardened runtime for notarization)
    for binary in clamd clamscan clamdscan freshclam; do
        if [ -f "$PYTHON_APP/Contents/Helpers/$binary" ]; then
            codesign --force --sign "$SIGN_IDENTITY" \
                --options runtime --timestamp \
                "$PYTHON_APP/Contents/Helpers/$binary" || {
                echo "    $binary signing failed"
                exit 1
            }
        fi
    done

    # Sign ClamAV shared libraries (all ClamAV-related dylibs including unrar, ssl, crypto)
    find "$PYTHON_APP/Contents/Frameworks" \( -name "libclamav*" -o -name "libfreshclam*" -o -name "libclammspack*" -o -name "libclamunrar*" -o -name "libcrypto*" -o -name "libssl*" -o -name "libjson-c*" \) -type f | while read -r lib; do
        codesign --force --sign "$SIGN_IDENTITY" \
            --options runtime --timestamp \
            "$lib" 2>/dev/null || true
    done

    echo "    ClamAV components signed"
fi

# 5a: Sign the system extension with distribution entitlements
echo "  - Signing system extension with Developer ID..."
codesign --force --sign "$SIGN_IDENTITY" \
    --options runtime \
    --timestamp \
    --entitlements "$NE_DIST_ENTITLEMENTS" \
    "$PYTHON_APP/Contents/Library/SystemExtensions/com.resistine.desktop.network-extension.systemextension" || {
    echo "  System Extension signing failed"
    exit 1
}
echo "    System Extension signed"

# 5b: Sign the CLI with distribution entitlements (reusing VPNXPC profile)
echo "  - Signing resistine-vpn-cli with Developer ID..."
codesign --force --sign "$SIGN_IDENTITY" \
    --options runtime \
    --timestamp \
    --entitlements "$CLI_DIST_ENTITLEMENTS" \
    "$PYTHON_APP/Contents/MacOS/resistine-vpn-cli" || {
    echo "  resistine-vpn-cli signing failed"
    exit 1
}
echo "    resistine-vpn-cli signed"

# 5d: Sign all PyInstaller frameworks/libraries
# NOTE: python.org Python bundles bare Tcl/Tk binaries (no file extension).
# We must sign ALL Mach-O binaries, not just *.so/*.dylib.
echo "  - Signing PyInstaller frameworks and shared libraries..."
find "$PYTHON_APP/Contents/Frameworks" "$PYTHON_APP/Contents/MacOS" \
    -type f \( -name "*.so" -o -name "*.dylib" -o -name "Python" -o -name "Tcl" -o -name "Tk" -o -name "tkhtml" \) | while read -r binary; do
    codesign --force --sign "$SIGN_IDENTITY" \
        --options runtime \
        --timestamp \
        "$binary" 2>/dev/null || {
        echo "    Warning: Failed to sign: $(basename "$binary")"
    }
done
echo "    Framework/library signing complete"

# 5e: Sign Sparkle.framework (inner-to-outer: deepest bundles first)
if [ -d "$PYTHON_APP/Contents/Frameworks/Sparkle.framework" ]; then
    SPARKLE_FW="$PYTHON_APP/Contents/Frameworks/Sparkle.framework"
    echo "  - Signing Sparkle.framework internals (inner-to-outer)..."

    # Sign XPC services (Downloader.xpc, Installer.xpc)
    # --preserve-metadata=entitlements: keeps Sparkle's original entitlements intact
    find "$SPARKLE_FW" -name "*.xpc" -type d | while read -r xpc_bundle; do
        codesign --force --sign "$SIGN_IDENTITY" \
            --options runtime --timestamp \
            --preserve-metadata=entitlements \
            "$xpc_bundle" 2>/dev/null || {
            echo "    Warning: Failed to sign: $(basename "$xpc_bundle")"
        }
    done

    # Sign Updater.app (Sparkle 2.9+ ships its own updater app)
    find "$SPARKLE_FW" -name "Updater.app" -type d | while read -r updater_app; do
        codesign --force --sign "$SIGN_IDENTITY" \
            --options runtime --timestamp \
            --preserve-metadata=entitlements \
            "$updater_app" 2>/dev/null || {
            echo "    Warning: Failed to sign Updater.app"
        }
    done

    # Sign the Autoupdate executable
    # CRITICAL: Autoupdate has com.apple.application-identifier which it needs
    # to register mach services for the installer agent connection.
    find "$SPARKLE_FW" -name "Autoupdate" -type f | while read -r autoupdate; do
        codesign --force --sign "$SIGN_IDENTITY" \
            --options runtime --timestamp \
            --preserve-metadata=entitlements \
            "$autoupdate" 2>/dev/null || {
            echo "    Warning: Failed to sign Autoupdate"
        }
    done

    # Sign the Sparkle.framework bundle itself (outermost)
    echo "  - Signing Sparkle.framework..."
    codesign --force --sign "$SIGN_IDENTITY" \
        --options runtime --timestamp \
        "$SPARKLE_FW" || {
        echo "  Sparkle.framework signing failed"
        exit 1
    }
    echo "    Sparkle.framework signed"
fi

# 5f: Sign the outer Resistine.app bundle
echo "  - Signing main Resistine.app bundle..."
codesign --force --sign "$SIGN_IDENTITY" \
    --options runtime \
    $ENTITLEMENTS_FLAG \
    --timestamp \
    "$PYTHON_APP" || {
    echo "  Main app signing failed"
    exit 1
}
echo "    Resistine.app signed"

# Verify all signatures
echo ""
echo "  Verifying signatures..."
VERIFY_FAILED=false

codesign --verify --verbose "$PYTHON_APP/Contents/Library/SystemExtensions/com.resistine.desktop.network-extension.systemextension" 2>&1 && \
    echo "    network-extension.systemextension: valid" || { echo "    network-extension.systemextension: INVALID"; VERIFY_FAILED=true; }

codesign --verify --verbose "$PYTHON_APP/Contents/MacOS/resistine-vpn-cli" 2>&1 && \
    echo "    resistine-vpn-cli: valid" || { echo "    resistine-vpn-cli: INVALID"; VERIFY_FAILED=true; }

if [ -d "$PYTHON_APP/Contents/Frameworks/Sparkle.framework" ]; then
    codesign --verify --verbose "$PYTHON_APP/Contents/Frameworks/Sparkle.framework" 2>&1 && \
        echo "    Sparkle.framework: valid" || { echo "    Sparkle.framework: INVALID"; VERIFY_FAILED=true; }
fi

if [ "$CLAMAV_AVAILABLE" = true ] && [ -d "$PYTHON_APP/Contents/Helpers/ResistineClamAV.app" ]; then
    codesign --verify --verbose "$PYTHON_APP/Contents/Helpers/ResistineClamAV.app" 2>&1 && \
        echo "    ResistineClamAV.app: valid" || { echo "    ResistineClamAV.app: INVALID"; VERIFY_FAILED=true; }
fi

codesign --verify --verbose=2 "$PYTHON_APP" 2>&1 && \
    echo "    Resistine.app: valid" || { echo "    Resistine.app: INVALID"; VERIFY_FAILED=true; }

if [ "$VERIFY_FAILED" = true ]; then
    echo ""
    echo "  Error: One or more signatures are invalid. Aborting."
    exit 1
fi

echo ""
echo "  All signatures verified"

# ============================================================
# Step 6: Create DMG
# ============================================================
echo ""
echo "Step 6: Creating DMG installer..."

if ! command -v create-dmg &> /dev/null; then
    echo "  - create-dmg not found. Installing via Homebrew..."
    if command -v brew &> /dev/null; then
        brew install create-dmg
    else
        echo "  Homebrew not found. Cannot create DMG."
        exit 1
    fi
fi

rm -f "$DIST_DIR/$APP_NAME-Installer.dmg"

BACKGROUND_FLAG=""
if [ -f "$PYTHON_UI_PATH/resources/installer-background.png" ]; then
    BACKGROUND_FLAG="--background $PYTHON_UI_PATH/resources/installer-background.png"
fi

ICON_FLAG=""
if [ -f "$PYTHON_UI_PATH/resources/icons/ResistineShield.png" ]; then
    ICON_FLAG="--volicon $PYTHON_UI_PATH/resources/icons/ResistineShield.png"
fi

create-dmg \
  --volname "$APP_NAME Installer" \
  $ICON_FLAG \
  --window-pos 200 120 \
  --window-size 800 400 \
  --icon-size 100 \
  --icon "$APP_NAME.app" 200 190 \
  --hide-extension "$APP_NAME.app" \
  --app-drop-link 600 185 \
  $BACKGROUND_FLAG \
  "$DIST_DIR/$APP_NAME-Installer.dmg" \
  "$PYTHON_APP" 2>&1 || {
    echo "  DMG creation had warnings but may have succeeded"
  }

if [ ! -f "$DIST_DIR/$APP_NAME-Installer.dmg" ]; then
    echo "  Error: DMG creation failed"
    exit 1
fi

DMG_SIZE=$(du -h "$DIST_DIR/$APP_NAME-Installer.dmg" | cut -f1)
echo "  DMG created: $DIST_DIR/$APP_NAME-Installer.dmg ($DMG_SIZE)"

# Sign the DMG
echo "  - Signing DMG..."
codesign --force --sign "$SIGN_IDENTITY" --timestamp "$DIST_DIR/$APP_NAME-Installer.dmg" || {
    echo "  DMG signing failed"
    exit 1
}
echo "  DMG signed"

# ============================================================
# Step 7: Notarization
# ============================================================
echo ""
echo "Step 7: Notarization..."

if [ "$SKIP_NOTARIZE" = true ]; then
    echo "  Skipping notarization (no credentials configured)"
    echo ""
    echo "  To notarize manually later:"
    echo "    xcrun notarytool submit $DIST_DIR/$APP_NAME-Installer.dmg \\"
    echo "      --keychain-profile \"resistine-notarize\" --wait"
    echo "    xcrun stapler staple $DIST_DIR/$APP_NAME-Installer.dmg"
else
    echo "  Submitting DMG for notarization..."
    xcrun notarytool submit "$DIST_DIR/$APP_NAME-Installer.dmg" \
        --keychain-profile "resistine-notarize" \
        --wait 2>&1 | tee /tmp/resistine-notarize-output.txt

    # Check if notarization succeeded
    if grep -q "status: Accepted" /tmp/resistine-notarize-output.txt; then
        echo "  Notarization accepted"

        echo "  Stapling notarization ticket..."
        xcrun stapler staple "$DIST_DIR/$APP_NAME-Installer.dmg" && {
            echo "  DMG stapled successfully"
        } || {
            echo "  Warning: Stapling failed (DMG is still notarized, just not stapled)"
        }
    else
        echo ""
        echo "  Notarization failed. Fetching detailed log..."

        # Extract submission ID from output
        SUBMISSION_ID=$(grep "id:" /tmp/resistine-notarize-output.txt | head -1 | awk '{print $2}')
        if [ -n "$SUBMISSION_ID" ]; then
            echo ""
            xcrun notarytool log "$SUBMISSION_ID" \
                --keychain-profile "resistine-notarize" 2>&1
        fi

        echo ""
        echo "  Fix the issues above and re-run this script."
        rm -f /tmp/resistine-notarize-output.txt
        exit 1
    fi

    rm -f /tmp/resistine-notarize-output.txt
fi

# Clean up temporary entitlements files
rm -f /tmp/ne-distribution.entitlements.plist /tmp/cli-distribution.entitlements.plist

# ============================================================
# Step 8: Install to /Applications
# ============================================================
echo ""
echo "Step 8: Installing to /Applications..."

if [ -d "/Applications/$APP_NAME.app" ]; then
    echo "  - Removing old /Applications/$APP_NAME.app..."
    rm -rf "/Applications/$APP_NAME.app" || {
        echo "  Failed to remove old app (may need sudo)"
    }
fi

cp -R "$PYTHON_APP" "/Applications/$APP_NAME.app" && {
    echo "  Installed to /Applications/$APP_NAME.app"
} || {
    echo "  Failed to install (may need sudo)"
}

# Register with LaunchServices and pluginkit so macOS discovers the network extension
echo "  - Registering app with LaunchServices..."
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "/Applications/$APP_NAME.app" 2>/dev/null || true

echo "  - Registering network extension with pluginkit..."
pluginkit -a "/Applications/$APP_NAME.app/Contents/Library/SystemExtensions/com.resistine.desktop.network-extension.systemextension" 2>/dev/null || true

# ── Prepare ClamAV system directories and config ──
# Daemons are registered at runtime via SMAppService (no sudo launchctl needed).
# But the system-level config and DB directories must exist before clamd starts.
LAUNCHD_BUNDLE="/Applications/$APP_NAME.app/Contents/Library/LaunchDaemons"
if [ -d "$LAUNCHD_BUNDLE" ]; then
    echo ""
    echo "  - Preparing ClamAV system directories..."

    # Create system-level ClamAV directories
    CLAMAV_SYSTEM_DIR="/Library/Application Support/Resistine/clamav"
    sudo mkdir -p "$CLAMAV_SYSTEM_DIR/log" "$CLAMAV_SYSTEM_DIR/db" "$CLAMAV_SYSTEM_DIR/run"

    # Generate system-level clamd.conf if it doesn't exist.
    # The daemon runs as root and needs its own config (separate from the
    # per-user config that the Resistine Desktop GUI generates).
    # The CI-built clamd has a hardcoded certs path from the GitHub Actions
    # runner that doesn't exist on end-user machines. Point at the bundled certs.
    CLAMAV_CERTS_DIR="/Applications/$APP_NAME.app/Contents/certs"

    if [ ! -f "$CLAMAV_SYSTEM_DIR/clamd.conf" ]; then
        cat > "$CLAMAV_SYSTEM_DIR/clamd.conf" << CLAMDEOF
# Auto-generated by Resistine installer — daemon config for clamd + clamonacc
# This config is used by the LaunchDaemon (system-level, runs as root).
LocalSocket $CLAMAV_SYSTEM_DIR/run/clamd.sock
PidFile $CLAMAV_SYSTEM_DIR/run/clamd.pid
DatabaseDirectory $CLAMAV_SYSTEM_DIR/db
LogFile $CLAMAV_SYSTEM_DIR/log/clamd.log
LogFileMaxSize 5M
LogTime yes
TemporaryDirectory /tmp
MaxDirectoryRecursion 20
FollowDirectorySymlinks yes
ExcludePath ^/proc
ExcludePath ^/sys
ExcludePath ^/dev
CVDCertsDirectory $CLAMAV_CERTS_DIR
OnAccessIncludePath /Users
OnAccessExcludePath /Users/Shared
OnAccessPrevention no
OnAccessExcludeRootUID yes
CLAMDEOF
        echo "    Created system clamd.conf"
    fi

    # Copy real DB files (not symlinks) to system DB dir so clamd can verify them
    USER_DB_DIR="$HOME/Library/Application Support/Resistine/clamav/db"
    if [ -d "$USER_DB_DIR" ]; then
        for cvd in "$USER_DB_DIR"/*.cvd "$USER_DB_DIR"/*.cld; do
            [ -f "$cvd" ] || continue
            cp "$cvd" "$CLAMAV_SYSTEM_DIR/db/" 2>/dev/null || true
        done
        echo "    Copied signature databases to system dir"
    fi

    echo "  ClamAV system directories ready (daemons registered via SMAppService at app launch)"
else
    echo "  - Skipping ClamAV setup (no plists in bundle)"
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo "==================================="
echo "  Distribution Build Complete!"
echo "==================================="
echo ""
echo "  Installer: $DIST_DIR/$APP_NAME-Installer.dmg"
echo "  App Bundle: $PYTHON_APP"
echo ""
if [ "$SKIP_NOTARIZE" = true ]; then
    echo "  Status: Signed with Developer ID (NOT notarized)"
    echo "  Run notarization manually before distributing."
else
    echo "  Status: Signed, Notarized, and Stapled"
    echo "  Ready for public distribution."
fi
echo ""
