#!/bin/bash

echo "🍎 Notarizing Resistine AI with Apple..."

# Load configuration from build_config.env
if [ -f "build_config.env" ]; then
    echo "📋 Loading configuration from build_config.env..."
    source build_config.env
else
    echo "⚠️  Warning: build_config.env not found. Using environment variables."
    echo "Make sure to set your credentials:"
    echo "export NOTARY_APPLE_ID='your-apple-id@example.com'"
    echo "export NOTARY_TEAM_ID='your-team-id'"
    echo "export NOTARY_PASSWORD='your-app-specific-password'"
fi
echo ""

# Check if app exists
if [ ! -d "dist/Resistine AI.app" ]; then
    echo "❌ Error: App not found. Run build_dmg.py first."
    exit 1
fi

# Create temporary DMG
echo "📦 Creating temporary DMG..."
TEMP_DMG="temp_notarize.dmg"
hdiutil create -volname "Resistine AI" -srcfolder "dist/Resistine AI.app" -ov -format UDZO "$TEMP_DMG"

if [ $? -ne 0 ]; then
    echo "❌ Failed to create temporary DMG"
    exit 1
fi

echo "📤 Submitting to Apple for notarization..."

# Get notarization credentials from environment variables
NOTARY_APPLE_ID="${NOTARY_APPLE_ID:-}"
NOTARY_TEAM_ID="${NOTARY_TEAM_ID:-}"

if [ -z "$NOTARY_APPLE_ID" ] || [ -z "$NOTARY_TEAM_ID" ] || [ -z "$NOTARY_PASSWORD" ]; then
    echo "❌ Error: NOTARY_APPLE_ID, NOTARY_TEAM_ID, and NOTARY_PASSWORD environment variables must be set."
    echo "Please set them with:"
    echo "  export NOTARY_APPLE_ID='your-apple-id@example.com'"
    echo "  export NOTARY_TEAM_ID='your-team-id'"
    echo "  export NOTARY_PASSWORD='your-app-specific-password'"
    exit 1
fi

xcrun notarytool submit "$TEMP_DMG" --apple-id "$NOTARY_APPLE_ID" --team-id "$NOTARY_TEAM_ID" --password "$NOTARY_PASSWORD" --wait

if [ $? -eq 0 ]; then
    echo "✅ Notarization successful!"
    
    # Staple the notarization ticket
    echo "📎 Stapling notarization ticket..."
    xcrun stapler staple "dist/Resistine AI.app"
    
    if [ $? -eq 0 ]; then
        echo "✅ Notarization ticket stapled!"
        
        # Create final notarized DMG
        echo "📦 Creating final notarized DMG..."
        mkdir -p installer_temp
        cp -R "dist/Resistine AI.app" installer_temp/
        ln -s /Applications installer_temp/Applications
        
        hdiutil create -volname "Resistine AI Installer" -srcfolder installer_temp -ov -format UDZO "Resistine AI-Notarized-1.0.0.dmg"
        
        if [ $? -eq 0 ]; then
            echo "✅ Final notarized DMG created: Resistine AI-Notarized-1.0.0.dmg"
            rm -rf installer_temp
        else
            echo "❌ Failed to create final DMG"
        fi
    else
        echo "❌ Failed to staple notarization ticket"
    fi
else
    echo "❌ Notarization failed!"
fi

# Clean up
rm -f "$TEMP_DMG"
echo "✅ Process complete!"