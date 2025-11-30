#!/usr/bin/env bash

# Description: This script runs the Resistine application.
# If the .venv folder does not exist, it will run the install.sh script first.
# Usage: ./run.sh

# Author: P3, Peres J. and the Resistine Team
# Copyright (c) Resistine 2025
# Licensed under the GNU General Public License v2 or later

# Print commands and their arguments as they are executed
set -x

# Exit immediately if a command exits with a non-zero status
set -e

# Check if .venv exists, if not run install.sh
if [ ! -d ".venv" ]; then
    echo ".venv folder not found. Running install.sh first..."
    ./install.sh
    exit 0
fi

# Detect the operating system
OS="$(uname -s)"
case "$OS" in
  Linux*)
    # Activate virtual environment
    source .venv/bin/activate
    
    # Install/update requirements if needed
    python3 -m pip install -q -r libraries/requirements-linux.txt
    
    # Run the application
    python3 main.py
    
    # Deactivate the virtual environment
    deactivate
    ;;

  # MACOS
  Darwin*)
    # Activate virtual environment
    source .venv/bin/activate

    # Make brewed Tcl/Tk visible (for Tkinter)
    if command -v brew >/dev/null; then
      export PATH="$(brew --prefix tcl-tk)/bin:$PATH"
      export LDFLAGS="-L$(brew --prefix tcl-tk)/lib"
      export CPPFLAGS="-I$(brew --prefix tcl-tk)/include"
    fi

    # Install/update requirements if needed
    python3 -m pip install -q -r libraries/requirements-mac.txt
    
    # Run the application
    python3 main.py
    
    # Deactivate the virtual environment
    deactivate
    ;;

  # Windows (Git Bash, Cygwin, MSYS2)
  CYGWIN*|MINGW*|MSYS*)
    # Activate virtual environment
    source .venv/Scripts/activate
    
    # Install/update requirements if needed
    python -m pip install -q -r libraries/requirements-windows.txt
    
    # Run the application
    python main.py
    
    # Deactivate the virtual environment
    deactivate
    ;;

  # Unsupported OS
  *)
    echo "Unsupported OS: $OS"
    exit 1
    ;;
esac
