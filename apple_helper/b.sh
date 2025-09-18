#!/bin/bash
echo "Building Apple Helper Tool for App Bundle..."

# Configuration variables
SIGNING_IDENTITY="Developer ID Application: Resistine GmbH (C7KSRZC3Q9)"
ENTITLEMENTS_FILE="../Resistine.entitlements"

# Check source files exist
if [ ! -f "main.swift" ] || [ ! -f "CodesignCheck.swift" ] || [ ! -f "com.resistine.plist" ]; then
    echo "❌ Required files not found"
    exit 1
fi

# Compile
echo "🔨 Compiling helper tool..."
swiftc -o ResistineHelper main.swift CodesignCheck.swift
if [ $? -ne 0 ]; then
    echo "❌ Compilation failed"
    exit 1
fi

# Sign
echo " Signing helper tool..."
codesign --force --sign "$SIGNING_IDENTITY" --timestamp --options runtime --entitlements "$ENTITLEMENTS_FILE" --identifier "com.resistine.helper" ResistineHelper

echo "✅ Helper ready for app bundle!"
