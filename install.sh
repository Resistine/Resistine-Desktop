#!/usr/bin/env bash

# Description: This script installs the dependencies and runs the application for Linux, MacOS, and Windows.
# It creates a virtual environment in the libraries/venv folder and installs the required Python packages.
# If the libraries/venv folder already exists, it prompts the user to delete it before proceeding.
# Usage: ./install.sh

# Author: Peres J., P3
# License: GNU General Public License v2.0 or later

# Print commands and their arguments as they are executed
set -x

# Exit immediately if a command exits with a non-zero status
set -e

# Check if the venv folder already exists in the libraries folder
if [ -d "libraries/venv" ]; then
    echo "libraries/venv folder already exists. Do you want to delete it? (y/n)"
    read delete_venv
    if [ "$delete_venv" == "y" ]; then
        rm -rf libraries/venv
    else
        echo "Please delete the libraries/venv folder and run this script again."
        exit 1
    fi
fi

# Detect the operating system
OS="$(uname -s)"
case "$OS" in
  Linux*)
    if [ -r /etc/os-release ]; then
      . /etc/os-release
    else
      echo "Cannot determine Linux distribution."
      exit 1
    fi

    distro_tags="$(printf '%s %s' "${ID}" "${ID_LIKE}")"
    case "$distro_tags" in
      *debian*|*ubuntu*)
        sudo apt update
        sudo apt install -y python3 python3-venv python3-pip python3-tk wireguard-tools
        ;;
      *rhel*|*fedora*|*centos*)
        pkg_mgr="$(command -v dnf || command -v yum || true)"
        if [ -z "$pkg_mgr" ]; then
          echo "dnf/yum not found."
          exit 1
        fi
        sudo "$pkg_mgr" install -y python3 python3-pip python3-tkinter wireguard-tools
        ;;
      *suse*)
        sudo zypper refresh
        sudo zypper install -y python3 python3-pip python3-tk wireguard-tools
        ;;
      *)
        # TODO: This should be improved to support more distros
        echo "Unsupported Linux distribution: ${ID:-unknown}"
        exit 1
        ;;
    esac

    python3 -m venv libraries/venv
    source libraries/venv/bin/activate
    python3 -m pip install -r libraries/requirements-linux.txt
    python3 main.py
    ;;

  # MACOS
  Darwin*)
    # TODO: Jackie

    # macOS (Homebrew)
    if ! command -v brew >/dev/null; then
      echo "Homebrew not found. Install from https://brew.sh"
      exit 1
    fi
    brew update
    brew install python@3.12 tcl-tk wireguard-tools

    # Ensure we use Homebrew's Python
    PY="$(brew --prefix python@3.12)/bin/python3"
    "$PY" -m venv libraries/venv
    source libraries/venv/bin/activate

    # Make brewed Tcl/Tk visible (for Tkinter)
    export PATH="$(brew --prefix tcl-tk)/bin:$PATH"
    export LDFLAGS="-L$(brew --prefix tcl-tk)/lib"
    export CPPFLAGS="-I$(brew --prefix tcl-tk)/include"

    python3 -m pip install -r libraries/requirements-mac.txt
    python3 main.py
    ;;

  # Windows (Git Bash, Cygwin, MSYS2)
  CYGWIN*|MINGW*|MSYS*)
    # TODO: This should be run instead:
    # build_win_simple.py in the branch Test-Windows-Version
    
    if ! command -v choco >/dev/null; then
      echo "Chocolatey not found. Install from https://chocolatey.org/install"
      exit 1
    fi
    choco upgrade chocolatey
    choco install -y python

    if [ ! -d "libraries/venv" ]; then
      python -m venv libraries/venv
    fi
    source libraries/venv/Scripts/activate
    python -m pip install -r libraries/requirements-windows.txt
    python main.py
    ;;

  # Unsupported OS
  *)
    # TODO: This should be improved to support more OS
    echo "Unsupported OS: $OS"
    exit 1
    ;;
esac

# Deactivate the virtual environment
deactivate
