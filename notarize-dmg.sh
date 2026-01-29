#!/bin/bash
set -e

# Notarize the Resistine DMG for distribution
# This eliminates Gatekeeper warnings when users download the DMG

# Configuration
APPLE_ID="jackie@resistine.com"  # Change to your Apple ID
TEAM_ID="C7KSRZC3Q9"             # Your team ID
DMG_PATH="dist/Resistine-Installer.dmg"

# Check if DMG exists
if [ ! -f "$DMG_PATH" ]; then
    echo "❌ Error: DMG not found at $DMG_PATH"
    exit 1
fi

# Check if DMG is signed
if ! codesign --verify "$DMG_PATH" 2>/dev/null; then
    echo "❌ Error: DMG is not signed. Run ./sign-dmg.sh first"
    exit 1
fi

echo "=== Notarizing Resistine DMG ==="
echo ""
echo "📝 Prerequisites:"
echo "  1. You need an Apple ID with Developer Program membership"
echo "  2. You need an app-specific password (create at appleid.apple.com)"
echo "  3. Store password in keychain (recommended):"
echo "     xcrun notarytool store-credentials \"resistine-notarize\" \\"
echo "       --apple-id \"$APPLE_ID\" \\"
echo "       --team-id \"$TEAM_ID\" \\"
echo "       --password \"<your-app-specific-password>\""
echo ""
echo "Press Enter to continue with notarization, or Ctrl+C to cancel..."
read

echo ""
echo "Submitting DMG for notarization..."
echo "This can take 2-10 minutes..."

# Option 1: Using stored credentials (recommended)
xcrun notarytool submit "$DMG_PATH" \
  --keychain-profile "resistine-notarize" \
  --wait

# Option 2: Using password directly (uncomment if you prefer)
# xcrun notarytool submit "$DMG_PATH" \
#   --apple-id "$APPLE_ID" \
#   --team-id "$TEAM_ID" \
#   --password "@keychain:AC_PASSWORD" \
#   --wait

echo ""
echo "✅ Notarization complete!"
echo ""
echo "Stapling notarization ticket to DMG..."
xcrun stapler staple "$DMG_PATH"

echo ""
echo "✅ DMG is now fully notarized and stapled!"
echo ""
echo "Verification:"
spctl --assess --type open --context context:primary-signature -v "$DMG_PATH"

echo ""
echo "=== Distribution Ready ==="
echo "Your DMG is now ready for public distribution."
echo "Users will NOT see any Gatekeeper warnings."
echo ""
echo "📦 Distributable DMG: $DMG_PATH"
echo ""
