#!/bin/sh

# --- Robust Path Calculation ---
if [ -z "$PROJECT_DIR" ]; then
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
fi

# Locate the WireGuardKitGo directory within the project
wireguard_go_dir=$(find "$PROJECT_DIR" -type d -name "WireGuardKitGo" | head -n 1)

if [ -z "$wireguard_go_dir" ] || [ ! -d "$wireguard_go_dir" ]; then
    echo "Error: Could not find WireGuardKitGo directory."
    exit 1
fi

# --- Build Environment Setup ---
export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin"
export CGO_ENABLED=1

cd "$wireguard_go_dir" || exit 1
echo "Building macOS library in: $wireguard_go_dir"

# Get macOS SDK Path
SDK_PATH=$(xcrun --sdk macosx --show-sdk-path)
if [ -z "$SDK_PATH" ]; then
    echo "Error: Could not find macOS SDK"
    exit 1
fi

# --- Build for macOS (Universal Binary) ---

# 1. Build for arm64
echo "Building for arm64 (macOS)..."
GOOS=darwin GOARCH=arm64 CGO_CFLAGS="-arch arm64 -isysroot $SDK_PATH" CGO_LDFLAGS="-arch arm64 -isysroot $SDK_PATH" \
go build -tags macos -ldflags=-w -trimpath -o "libwireguard_arm64.a" -buildmode=c-archive

# 2. Build for x86_64
echo "Building for x86_64 (macOS)..."
GOOS=darwin GOARCH=amd64 CGO_CFLAGS="-arch x86_64 -isysroot $SDK_PATH" CGO_LDFLAGS="-arch x86_64 -isysroot $SDK_PATH" \
go build -tags macos -ldflags=-w -trimpath -o "libwireguard_x86_64.a" -buildmode=c-archive

# 3. Combine into a Universal Binary
echo "Creating universal binary..."
lipo -create "libwireguard_arm64.a" "libwireguard_x86_64.a" -output "libwg-go.a"

# 4. Move to the script directory
cp "libwg-go.a" "$PROJECT_DIR/script/libwg-go.a"

echo "✅ Universal library created at: $PROJECT_DIR/script/libwg-go.a"
