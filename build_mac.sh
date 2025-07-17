#!/bin/bash

# Build script for macOS
set -e

echo "Building Resistine for macOS..."



# Create and activate venv if needed
if [ ! -d "libraries/venv" ]; then
    python3 -m venv libraries/venv
fi

source libraries/venv/bin/activate

# Install dependencies and PyInstaller
brew update
 brew install python3 python-tk wireguard-tools
        
pip install pyinstaller
pip install -r libraries/requirements-mac.txt
# Clean previous builds
rm -rf build dist



# Build the app with PyInstaller


pyinstaller \
  --windowed \
  --name "Resistine" \
  --icon "resources/icons/icon.ico" \
  --add-data "resources:resources" \
  --add-data "plugins:plugins" \
  --add-data "utils:utils" \
  --hidden-import openai \
  --hidden-import cryptography.fernet \
  --hidden-import webbrowser \
  --hidden-import keyring \
  --hidden-import markdown \
  --hidden-import html2text \
  main.py
echo "Build complete! Check the dist/ directory for your app."