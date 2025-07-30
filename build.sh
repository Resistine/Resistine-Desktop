#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Resistine AI - Build & Notarize Script${NC}"
echo "================================================"

# Load configuration
if [ -f "build_config.env" ]; then
    echo "📋 Loading configuration from build_config.env..."
    source build_config.env
    echo "✅ Configuration loaded"
else
    echo -e "${YELLOW}⚠️  Warning: build_config.env not found${NC}"
    echo "   Make sure to set your credentials manually"
fi

# Step 1: Build the app
echo ""
echo -e "${GREEN}📦 Step 1: Building the application...${NC}"
echo "----------------------------------------"

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf dist build
rm -f *.spec

# Install dependencies
echo "📦 Installing dependencies..."
pip3 install -r libraries/requirements-mac.txt

# Run the build script
echo "🔨 Building with PyInstaller..."
python3 build_dmg_simple.py

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Build failed!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Build completed successfully!${NC}"

# Step 2: Notarize the app
echo ""
echo -e "${GREEN}�� Step 2: Notarizing the application...${NC}"
echo "----------------------------------------"

# Check if app exists
if [ ! -d "dist/Resistine AI.app" ]; then
    echo -e "${RED}❌ Error: App not found. Build failed.${NC}"
    exit 1
fi

# Check for notarization credentials
if [ -z "$NOTARY_APPLE_ID" ] || [ -z "$NOTARY_TEAM_ID" ] || [ -z "$NOTARY_PASSWORD" ]; then
    echo -e "${YELLOW}⚠️  Notarization credentials not found${NC}"
    echo "   Set NOTARY_APPLE_ID, NOTARY_TEAM_ID, and NOTARY_PASSWORD in build_config.env"
    echo "   Skipping notarization..."
    echo ""
    echo -e "${GREEN}�� Build completed! (Not notarized)${NC}"
    echo "�� App location: dist/Resistine AI.app"
    echo "💿 DMG location: Resistine AI-1.0.0.dmg"
    exit 0
fi

# Create temporary DMG for notarization
echo "�� Creating temporary DMG for notarization..."
TEMP_DMG="temp_notarize.dmg"
hdiutil create -volname "Resistine AI" -srcfolder "dist/Resistine AI.app" -ov -format UDZO "$TEMP_DMG"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to create temporary DMG${NC}"
    exit 1
fi

# Submit to Apple for notarization
echo "📤 Submitting to Apple for notarization..."
xcrun notarytool submit "$TEMP_DMG" --apple-id "$NOTARY_APPLE_ID" --team-id "$NOTARY_TEAM_ID" --password "$NOTARY_PASSWORD" --wait

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Notarization successful!${NC}"
    
    # Staple the notarization ticket
    echo "📎 Stapling notarization ticket..."
    xcrun stapler staple "dist/Resistine AI.app"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Notarization ticket stapled!${NC}"
        
        # Create final notarized DMG
        echo "�� Creating final notarized DMG..."
        mkdir -p installer_temp
        cp -R "dist/Resistine AI.app" installer_temp/
        ln -s /Applications installer_temp/Applications
        
        hdiutil create -volname "Resistine AI Installer" -srcfolder installer_temp -ov -format UDZO "Resistine AI-Notarized-1.0.0.dmg"
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✅ Final notarized DMG created!${NC}"
            rm -rf installer_temp
        else
            echo -e "${RED}❌ Failed to create final DMG${NC}"
        fi
    else
        echo -e "${RED}❌ Failed to staple notarization ticket${NC}"
    fi
else
    echo -e "${RED}❌ Notarization failed!${NC}"
fi

# Clean up
rm -f "$TEMP_DMG"

# Final summary
echo ""
echo -e "${GREEN}🎉 Build Process Complete!${NC}"
echo "================================"
echo ""
echo "📦 Output files:"
if [ -f "Resistine AI-Notarized-1.0.0.dmg" ]; then
    echo -e "   ${GREEN}✅ Resistine AI-Notarized-1.0.0.dmg (Ready for distribution)${NC}"
elif [ -f "Resistine AI-1.0.0.dmg" ]; then
    echo -e "   ${GREEN}✅ Resistine AI-1.0.0.dmg (Signed but not notarized)${NC}"
fi
echo "   �� App location: dist/Resistine AI.app"
echo ""
echo -e "${GREEN}✨ All done!${NC}"

