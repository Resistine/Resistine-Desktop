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
PYTHON_UI_PATH="$SCRIPT_DIR"
VPN_PROJECT_PATH="$PYTHON_UI_PATH/vpn-apple"

# Validate paths exist
echo "Checking project structure..."
if [ ! -d "$PYTHON_UI_PATH" ]; then
    echo "  Error: Python UI directory not found at: $PYTHON_UI_PATH"
    exit 1
fi

if [ ! -d "$VPN_PROJECT_PATH" ]; then
    echo "  Error: VPN project directory not found at: $VPN_PROJECT_PATH"
    exit 1
fi

echo "  Found Python UI: $PYTHON_UI_PATH"
echo "  Found VPN project: $VPN_PROJECT_PATH"
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

# Provisioning Profile UUIDs (from provisioning-profiles folder)
NE_PROFILE_UUID="df58a6c4-c227-435a-b136-d508374cf32c"
CLI_PROFILE_UUID="924cf30e-5ec1-481a-a37b-1256b8447e22"

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
# Step 2: Build Swift Components (VPN)
# ============================================================
echo "Step 2: Building Swift components..."
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
pip install -q -r libraries/requirements-mac.txt

if [ ! -f "Resistine.spec" ]; then
    echo "  Error: Resistine.spec not found in $PYTHON_UI_PATH"
    exit 1
fi

rm -rf dist/Resistine dist/Resistine.app

echo "  - Building with PyInstaller..."
pyinstaller Resistine.spec --clean --noconfirm

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
VPN_ARCHIVE="$BUILD_DIR/wireguard-apple.xcarchive/Products/Applications/wireguard-apple.app"

if [ ! -d "$PYTHON_APP" ]; then
    echo "  Error: Python app bundle not found at $PYTHON_APP"
    exit 1
fi

if [ ! -d "$VPN_ARCHIVE" ]; then
    echo "  Error: VPN archive not found at $VPN_ARCHIVE"
    exit 1
fi

# Create Apple-standard directories
mkdir -p "$PYTHON_APP/Contents/PlugIns"
mkdir -p "$PYTHON_APP/Contents/Library/SystemExtensions"

# --- Copy CLI to Contents/MacOS/ ---
# IMPORTANT: The CLI must be in Contents/MacOS/ because
# NSXPCConnection(serviceName:) (used indirectly by some frameworks) 
# and other bundle detection logic relies on the process being 
# in the main app's MacOS folder.
# --- Copy CLI to Contents/MacOS/ as a Bundle ---
# To support restricted entitlements (App Groups) in the CLI, it must have a 
# provisioning profile embedded. Standalone binaries cannot easily have embedded 
# profiles, so we wrap it in a nested bundle: ResistineCLI.app

echo "  - Packaging resistine-vpn-cli into nested bundle..."
CLI_APP="$PYTHON_APP/Contents/MacOS/ResistineCLI.app"
mkdir -p "$CLI_APP/Contents/MacOS"

# Find CLI in archive
CLI_SOURCE=$(find "$VPN_ARCHIVE" -name "resistine-vpn-cli" -type f | grep -v "dSYM" | grep "/MacOS/" | head -1)
if [ -z "$CLI_SOURCE" ] || [ ! -f "$CLI_SOURCE" ]; then
    echo "  Error: resistine-vpn-cli not found in archive"
    exit 1
fi

echo "    Found CLI at: $CLI_SOURCE"
cp "$CLI_SOURCE" "$CLI_APP/Contents/MacOS/resistine-vpn-cli"

# --- Copy Network Extension to Contents/Library/SystemExtensions/ ---
# CRITICAL: System Extensions MUST use .systemextension extension, not .appex!
echo "  - Copying network-extension to Contents/Library/SystemExtensions/..."

NE_SOURCE=$(find "$VPN_ARCHIVE" -name "*network-extension*" \( -name "*.appex" -o -name "*.systemextension" \) -type d | grep -v "dSYM" | head -1)

if [ -z "$NE_SOURCE" ]; then
    echo "  Error: Network Extension not found in archive"
    exit 1
fi

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
# Step 5: Embed Developer ID provisioning profiles & sign
# ============================================================
echo ""
echo "Step 5: Embedding Developer ID provisioning profiles & signing..."

PROFILES_DIR="$PYTHON_UI_PATH/provisioning-profiles"
NE_PROFILE="$PROFILES_DIR/Mac_Network_Ext.provisionprofile"
XPC_PROFILE="$PROFILES_DIR/Mac_VPNXPC.provisionprofile"
MAIN_PROFILE="$PROFILES_DIR/Mac_Desktop.provisionprofile"

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

# Create symlink for compatibility
# Python code expects resistine-vpn-cli at ../MacOS/resistine-vpn-cli
echo "  - Creating symlink for CLI..."
ln -sf "ResistineCLI.app/Contents/MacOS/resistine-vpn-cli" "$PYTHON_APP/Contents/MacOS/resistine-vpn-cli"

# --- Copy Sparkle.framework for auto-updates ---
echo "  - Copying Sparkle.framework..."
SPARKLE_SOURCE="$PYTHON_UI_PATH/vpn-apple/Sparkle.framework"
if [ -d "$SPARKLE_SOURCE" ]; then
    mkdir -p "$PYTHON_APP/Contents/Frameworks"
    cp -R "$SPARKLE_SOURCE" "$PYTHON_APP/Contents/Frameworks/Sparkle.framework"
    echo "    Sparkle.framework copied"
else
    echo "    Warning: Sparkle.framework not found at $SPARKLE_SOURCE — skipping auto-update"
fi


# Locate entitlements files
ENTITLEMENTS_FILE="$PYTHON_UI_PATH/Resistine.entitlements"
CLI_ENTITLEMENTS="$VPN_PROJECT_PATH/resistine-vpn-cli/entitlements.plist"

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


# Verify CLI entitlements exist
if [ ! -f "$CLI_ENTITLEMENTS" ]; then
    echo "  Error: CLI entitlements file not found: $CLI_ENTITLEMENTS"
    exit 1
fi

ENTITLEMENTS_FLAG=""
if [ -f "$ENTITLEMENTS_FILE" ]; then
    ENTITLEMENTS_FLAG="--entitlements $ENTITLEMENTS_FILE"
fi

# --- Sign innermost components first, then work outward ---
# Order matters: sign binaries inside bundles before signing the bundle itself.

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
    find "$SPARKLE_FW" -name "*.xpc" -type d | while read -r xpc_bundle; do
        codesign --force --sign "$SIGN_IDENTITY" \
            --options runtime --timestamp "$xpc_bundle" 2>/dev/null || {
            echo "    Warning: Failed to sign: $(basename "$xpc_bundle")"
        }
    done

    # Sign Updater.app (Sparkle 2.9+ ships its own updater app)
    find "$SPARKLE_FW" -name "Updater.app" -type d | while read -r updater_app; do
        codesign --force --sign "$SIGN_IDENTITY" \
            --options runtime --timestamp "$updater_app" 2>/dev/null || {
            echo "    Warning: Failed to sign Updater.app"
        }
    done

    # Sign the Autoupdate executable
    find "$SPARKLE_FW" -name "Autoupdate" -type f | while read -r autoupdate; do
        codesign --force --sign "$SIGN_IDENTITY" \
            --options runtime --timestamp "$autoupdate" 2>/dev/null || {
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
if [ -f "$PYTHON_UI_PATH/ResistineSheild.png" ]; then
    ICON_FLAG="--volicon $PYTHON_UI_PATH/ResistineSheild.png"
elif [ -f "$PYTHON_UI_PATH/resources/ResistineSheild.png" ]; then
    ICON_FLAG="--volicon $PYTHON_UI_PATH/resources/ResistineSheild.png"
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
rm -f /tmp/ne-distribution.entitlements.plist /tmp/xpc-distribution.entitlements.plist

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
