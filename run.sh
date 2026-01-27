#!/usr/bin/env bash

# Description: This script updates all dependencies and runs the Resistine application.
# If the .venv folder does not exist, it will run the install.sh script first.
# Usage: ./run.sh

# Author: P3 and the Resistine Team
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

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
	source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
	source .venv/Scripts/activate
else
	echo "Error: Cannot find activation script. Please run install.sh."
	exit 1
fi

# Detect the operating system
OS="$(uname -s)"
case "$OS" in
Linux*)
	# Install/update requirements if needed
	python3 -m pip install -U -q -r libraries/requirements-linux.txt
	;;

# MACOS
Darwin*)
	# Make brewed Tcl/Tk visible (for Tkinter)
	if command -v brew >/dev/null; then
		export PATH="$(brew --prefix tcl-tk)/bin:$PATH"
		export LDFLAGS="-L$(brew --prefix tcl-tk)/lib"
		export CPPFLAGS="-I$(brew --prefix tcl-tk)/include"
		# Add Homebrew lib path for Cairo and other libraries
		export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"
	fi

	# Install/update requirements if needed
	python3 -m pip install -U -q -r libraries/requirements-mac.txt
	;;

# Windows (Git Bash, Cygwin, MSYS2)
CYGWIN* | MINGW* | MSYS*)
	# Install/update requirements if needed
	python -m pip install -U -q -r libraries/requirements-windows.txt
	;;

# Unsupported OS
*)
	echo "Unsupported OS: $OS"
	exit 1
	;;
esac

# Run the application
python main.py "$@"

# Deactivate the virtual environment
deactivate
