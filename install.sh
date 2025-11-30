#!/usr/bin/env bash

# Description: This script installs the dependencies and runs the application for Linux, MacOS, and Windows.
# It creates a virtual environment in the libraries/venv folder and installs the required Python packages.
# If the libraries/venv folder already exists, it prompts the user to delete it before proceeding.
# Usage: ./install.sh

# Author: P3, Peres J. and the Resistine Team
# Copyright (c) Resistine 2025
# Licensed under the GNU General Public License v2 or later

# Print commands and their arguments as they are executed
set -x

# Exit immediately if a command exits with a non-zero status
set -e

# Check if the venv folder already exists in the libraries folder
if [ -d ".venv" ]; then
    echo ".venv folder already exists. Do you want to delete it? (y/n)"
    read delete_venv
    if [ "$delete_venv" == "y" ]; then
        rm -rf .venv
    else
        echo "Please delete the .venv folder and run this script again."
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
        # Check if packages are already installed
        PACKAGES_TO_INSTALL=""
        for pkg in python3 python3-venv python3-pip python3-tk wireguard-tools; do
          if ! dpkg -s "$pkg" &>/dev/null; then
            PACKAGES_TO_INSTALL="$PACKAGES_TO_INSTALL $pkg"
          fi
        done
        
        if [ -n "$PACKAGES_TO_INSTALL" ]; then
          echo "Installing missing packages:$PACKAGES_TO_INSTALL"
          sudo apt update
          sudo apt install -y $PACKAGES_TO_INSTALL
        else
          echo "All required packages are already installed."
        fi
        ;;
      *rhel*|*fedora*|*centos*)
        pkg_mgr="$(command -v dnf || command -v yum || true)"
        if [ -z "$pkg_mgr" ]; then
          echo "dnf/yum not found."
          exit 1
        fi
        
        # Check if packages are already installed
        PACKAGES_TO_INSTALL=""
        for pkg in python3 python3-pip python3-tkinter wireguard-tools; do
          if ! rpm -q "$pkg" &>/dev/null; then
            PACKAGES_TO_INSTALL="$PACKAGES_TO_INSTALL $pkg"
          fi
        done
        
        if [ -n "$PACKAGES_TO_INSTALL" ]; then
          echo "Installing missing packages:$PACKAGES_TO_INSTALL"
          sudo "$pkg_mgr" install -y $PACKAGES_TO_INSTALL
        else
          echo "All required packages are already installed."
        fi
        ;;
      *suse*)
        # Check if packages are already installed
        PACKAGES_TO_INSTALL=""
        for pkg in python3 python3-pip python3-tk wireguard-tools; do
          if ! rpm -q "$pkg" &>/dev/null; then
            PACKAGES_TO_INSTALL="$PACKAGES_TO_INSTALL $pkg"
          fi
        done
        
        if [ -n "$PACKAGES_TO_INSTALL" ]; then
          echo "Installing missing packages:$PACKAGES_TO_INSTALL"
          sudo zypper refresh
          sudo zypper install -y $PACKAGES_TO_INSTALL
        else
          echo "All required packages are already installed."
        fi
        ;;
      *)
        # TODO: This should be improved to support more distros
        echo "Unsupported Linux distribution: ${ID:-unknown}"
        exit 1
        ;;
    esac

    # Create venv as regular user (not with sudo)
    python3 -m venv .venv
    ;;

  # MACOS
  Darwin*)
    # TODO: Jackie

    # macOS (Homebrew)
    if ! command -v brew >/dev/null; then
      echo "Homebrew not found. Install from https://brew.sh"
      exit 1
    fi
    
    # Check if packages are already installed
    PACKAGES_TO_INSTALL=""
    for pkg in python@3.12 tcl-tk wireguard-tools; do
      if ! brew list "$pkg" &>/dev/null; then
        PACKAGES_TO_INSTALL="$PACKAGES_TO_INSTALL $pkg"
      fi
    done
    
    if [ -n "$PACKAGES_TO_INSTALL" ]; then
      echo "Installing missing packages:$PACKAGES_TO_INSTALL"
      brew update
      brew install $PACKAGES_TO_INSTALL
    else
      echo "All required packages are already installed."
    fi

    # Ensure we use Homebrew's Python
    PY="$(brew --prefix python@3.12)/bin/python3"
    "$PY" -m venv .venv
    ;;

  # Windows (Git Bash, Cygwin, MSYS2)
  CYGWIN*|MINGW*|MSYS*)
    # TODO: This should be run instead:
    # build_win_simple.py in the branch Test-Windows-Version
    
    if ! command -v choco >/dev/null; then
      echo "Chocolatey not found. Install from https://chocolatey.org/install"
      exit 1
    fi
    
    # Check if Python is already installed
    if ! choco list --local-only python --exact &>/dev/null | grep -q "1 packages installed"; then
      echo "Installing Python..."
      choco upgrade chocolatey
      choco install -y python
    else
      echo "Python is already installed."
    fi

    if [ ! -d ".venv" ]; then
      python -m venv .venv
    fi
    ;;

  # Unsupported OS
  *)
    # TODO: This should be improved to support more OS
    echo "Unsupported OS: $OS"
    exit 1
    ;;
esac

# Installation complete, now run the application
echo ""
echo "Installation complete! Starting the application..."
echo ""
./run.sh
