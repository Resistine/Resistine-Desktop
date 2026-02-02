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
  -allowProvisioningUpdates \
  CODE_SIGN_STYLE="Automatic" \
  DEVELOPMENT_TEAM="$TEAM_ID"

echo "  Swift components built"

# ============================================================
# Step 3: Build Python UI with PyInstaller
# ============================================================
echo ""
echo "Step 3: Building Python UI..."
cd "$PYTHON_UI_PATH"

if [ ! -d ".venv" ]; then
    echo "  - Creating virtual environment..."
    python3 -m venv .venv
fi

echo "  - Installing dependencies..."
source .venv/bin/activate
pip install -q -r libraries/requirements-mac.txt

if [ ! -f "Resistine.spec" ]; then
    echo "  Error: Resistine.spec not found in $PYTHON_UI_PATH"
    exit 1
fi

rm -rf dist/Resistine dist/Resistine.app

echo "  - Building with PyInstaller..."
pyinstaller Resistine.spec --clean

echo "  Python UI built"

# ============================================================
# Step 4: Place VPN components directly in Resistine.app bundle
# ============================================================
# Apple bundle structure requirements (from Apple documentation):
#   - App Extensions (.appex): Contents/PlugIns/
#   - XPC Services (.xpc): Contents/XPCServices/
#   - Helper Tools / CLI: Contents/Helpers/ or Contents/MacOS/
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
mkdir -p "$PYTHON_APP/Contents/XPCServices"

# --- Copy CLI to Contents/MacOS/ ---
# IMPORTANT: The CLI must be in Contents/MacOS/ (not Contents/Helpers/) because
# NSXPCConnection(serviceName:) relies on launchd to discover XPC services.
# launchd associates a process with its parent app bundle by checking if the
# binary is in Contents/MacOS/. Binaries in Contents/Helpers/ are NOT associated
# with the app bundle, so launchd can't find the XPC service for them.
echo "  - Copying resistine-vpn-cli to Contents/MacOS/..."
if [ ! -f "$VPN_ARCHIVE/Contents/MacOS/resistine-vpn-cli" ]; then
    echo "  Error: resistine-vpn-cli not found in archive"
    exit 1
fi
cp "$VPN_ARCHIVE/Contents/MacOS/resistine-vpn-cli" "$PYTHON_APP/Contents/MacOS/"

# --- Copy Network Extension to Contents/PlugIns/ ---
echo "  - Copying network-extension.appex to Contents/PlugIns/..."
if [ ! -d "$VPN_ARCHIVE/Contents/PlugIns/network-extension.appex" ]; then
    echo "  Error: network-extension.appex not found in archive"
    exit 1
fi
cp -R "$VPN_ARCHIVE/Contents/PlugIns/network-extension.appex" "$PYTHON_APP/Contents/PlugIns/"

# --- Copy XPC Service to Contents/XPCServices/ ---
echo "  - Copying ResistineVPNXPC.xpc to Contents/XPCServices/..."
if [ ! -d "$VPN_ARCHIVE/Contents/XPCServices/ResistineVPNXPC.xpc" ]; then
    echo "  Error: ResistineVPNXPC.xpc not found in archive"
    exit 1
fi
cp -R "$VPN_ARCHIVE/Contents/XPCServices/ResistineVPNXPC.xpc" "$PYTHON_APP/Contents/XPCServices/"

# Verify all components are in place
echo "  - Verifying bundle structure..."
if [ ! -f "$PYTHON_APP/Contents/MacOS/resistine-vpn-cli" ]; then
    echo "  Error: CLI not in Contents/MacOS/"
    exit 1
fi
if [ ! -d "$PYTHON_APP/Contents/PlugIns/network-extension.appex" ]; then
    echo "  Error: Network Extension not in Contents/PlugIns/"
    exit 1
fi
if [ ! -d "$PYTHON_APP/Contents/XPCServices/ResistineVPNXPC.xpc" ]; then
    echo "  Error: XPC Service not in Contents/XPCServices/"
    exit 1
fi

echo "  VPN components placed in Apple-standard locations"
echo "     - CLI: Contents/MacOS/resistine-vpn-cli"
echo "     - Network Extension: Contents/PlugIns/network-extension.appex"
echo "     - XPC Service: Contents/XPCServices/ResistineVPNXPC.xpc"

# ============================================================
# Step 5: Embed Developer ID provisioning profiles & sign
# ============================================================
echo ""
echo "Step 5: Embedding Developer ID provisioning profiles & signing..."

# Developer ID provisioning profiles (required for restricted entitlements)
PROFILES_DIR="$PYTHON_UI_PATH/provisioning-profiles"
NE_PROFILE="$PROFILES_DIR/Mac_Network_Ext.provisionprofile"
XPC_PROFILE="$PROFILES_DIR/Mac_VPNXPC.provisionprofile"

if [ ! -f "$NE_PROFILE" ]; then
    echo "  Error: Network Extension Developer ID profile not found at: $NE_PROFILE"
    echo "  Download it from Apple Developer Portal and place it in provisioning-profiles/"
    exit 1
fi

if [ ! -f "$XPC_PROFILE" ]; then
    echo "  Error: VPNXPC Service Developer ID profile not found at: $XPC_PROFILE"
    echo "  Download it from Apple Developer Portal and place it in provisioning-profiles/"
    exit 1
fi

# Embed Developer ID profiles into components (at their new Apple-standard locations)
echo "  - Embedding Developer ID profile into network-extension.appex..."
cp "$NE_PROFILE" "$PYTHON_APP/Contents/PlugIns/network-extension.appex/Contents/embedded.provisionprofile"

echo "  - Embedding Developer ID profile into ResistineVPNXPC.xpc..."
cp "$XPC_PROFILE" "$PYTHON_APP/Contents/XPCServices/ResistineVPNXPC.xpc/Contents/embedded.provisionprofile"

# Locate entitlements files
ENTITLEMENTS_FILE="$PYTHON_UI_PATH/Resistine.entitlements"
CLI_ENTITLEMENTS="$VPN_PROJECT_PATH/resistine-vpn-cli/entitlements.plist"

# For Developer ID distribution, networkextension entitlements need the
# -systemextension suffix. The entitlements must also include
# com.apple.application-identifier and com.apple.developer.team-identifier
# to match the embedded provisioning profile, otherwise signature
# validation fails ("Signature check failed").
NE_DIST_ENTITLEMENTS="/tmp/ne-distribution.entitlements.plist"
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

XPC_DIST_ENTITLEMENTS="/tmp/xpc-distribution.entitlements.plist"
cat > "$XPC_DIST_ENTITLEMENTS" << ENTEOF
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

# 5a: Sign the network extension with distribution entitlements
echo "  - Signing network-extension.appex with Developer ID..."
codesign --force --sign "$SIGN_IDENTITY" \
    --options runtime \
    --timestamp \
    --entitlements "$NE_DIST_ENTITLEMENTS" \
    "$PYTHON_APP/Contents/PlugIns/network-extension.appex" || {
    echo "  network-extension.appex signing failed"
    exit 1
}
echo "    network-extension.appex signed"

# 5b: Sign the XPC service with distribution entitlements
echo "  - Signing ResistineVPNXPC.xpc with Developer ID..."
codesign --force --sign "$SIGN_IDENTITY" \
    --options runtime \
    --timestamp \
    --entitlements "$XPC_DIST_ENTITLEMENTS" \
    "$PYTHON_APP/Contents/XPCServices/ResistineVPNXPC.xpc" || {
    echo "  ResistineVPNXPC.xpc signing failed"
    exit 1
}
echo "    ResistineVPNXPC.xpc signed"

# 5c: Sign the CLI
echo "  - Signing resistine-vpn-cli with Developer ID..."
codesign --force --sign "$SIGN_IDENTITY" \
    --options runtime \
    --timestamp \
    --entitlements "$CLI_ENTITLEMENTS" \
    "$PYTHON_APP/Contents/MacOS/resistine-vpn-cli" || {
    echo "  resistine-vpn-cli signing failed"
    exit 1
}
echo "    resistine-vpn-cli signed"

# 5d: Sign all PyInstaller frameworks/libraries
echo "  - Signing PyInstaller frameworks and shared libraries..."
find "$PYTHON_APP/Contents/Frameworks" "$PYTHON_APP/Contents/MacOS" \
    -type f \( -name "*.so" -o -name "*.dylib" -o -name "Python" \) | while read -r binary; do
    codesign --force --sign "$SIGN_IDENTITY" \
        --options runtime \
        --timestamp \
        "$binary" 2>/dev/null || {
        echo "    Warning: Failed to sign: $(basename "$binary")"
    }
done
echo "    Framework/library signing complete"

# 5e: Sign the outer Resistine.app bundle
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

codesign --verify --verbose "$PYTHON_APP/Contents/PlugIns/network-extension.appex" 2>&1 && \
    echo "    network-extension.appex: valid" || { echo "    network-extension.appex: INVALID"; VERIFY_FAILED=true; }

codesign --verify --verbose "$PYTHON_APP/Contents/XPCServices/ResistineVPNXPC.xpc" 2>&1 && \
    echo "    ResistineVPNXPC.xpc: valid" || { echo "    ResistineVPNXPC.xpc: INVALID"; VERIFY_FAILED=true; }

codesign --verify --verbose "$PYTHON_APP/Contents/MacOS/resistine-vpn-cli" 2>&1 && \
    echo "    resistine-vpn-cli: valid" || { echo "    resistine-vpn-cli: INVALID"; VERIFY_FAILED=true; }

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
pluginkit -a "/Applications/$APP_NAME.app/Contents/PlugIns/network-extension.appex" 2>/dev/null || true

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
