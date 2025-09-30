#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/cli"

# Build a small Swift CLI that links against Foundation only
OUT="ResistCli"

swiftc -O -sdk $(xcrun --show-sdk-path --sdk macosx) -framework Foundation main.swift -o "$OUT"
echo "Built $OUT"


