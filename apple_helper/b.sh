#!/bin/bash
echo "Building Apple Helper Tool for App Bundle..."


# Check source files exist
if [ ! -f "main.swift" ] || [ ! -f "CodesignCheck.swift" ] || [ ! -f "com.resistine.plist" ]; then
    echo "❌ Required files not found"
    exit 1
fi

# Compile
echo "🔨 Compiling helper tool..."
swiftc -o ResistineHelper main.swift CodesignCheck.swift \
    -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker helperInfo.plist
if [ $? -ne 0 ]; then
    echo "❌ Compilation failed"
    exit 1
fi

echo "✅ Helper ready for app bundle!"